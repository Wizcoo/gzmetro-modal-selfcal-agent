#include "ModalSelfCal.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
template<class T> void read_value(std::istream& f,T& v){f.read(reinterpret_cast<char*>(&v),sizeof(v));if(!f)throw std::runtime_error("truncated input");}
void need(bool v,const std::string& error){if(!v)throw std::runtime_error(error);}
std::string missing_guard(std::string blob){
  auto at=blob.find("\nvel=");need(at!=std::string::npos,"velocity component absent in original");blob.replace(at+1,3,"bad");
  uint64_t hash=14695981039346656037ULL;for(size_t i=0;i<blob.size()-8;++i){hash^=static_cast<unsigned char>(blob[i]);hash*=1099511628211ULL;}
  for(int i=0;i<8;++i)blob[blob.size()-8+i]=char(hash>>(8*i));return blob;
}
void eq(const std::vector<double>& a,const std::vector<double>& b,const char* label){
  need(a.size()==b.size(),std::string(label)+" size mismatch");
  for(size_t i=0;i<a.size();++i)need(a[i]==b[i]||(std::isnan(a[i])&&std::isnan(b[i])),std::string(label)+" value mismatch at "+std::to_string(i));
}
void compare(const ModalSelfCalResult& a,const ModalSelfCalResult& b){
  need(a.output_ready==b.output_ready&&a.duplicate==b.duplicate&&a.replayed==b.replayed,"result publication flags differ");
  eq(a.x,b.x,"x");eq(a.y,b.y,"y");eq(a.correction_x,b.correction_x,"correction_x");eq(a.correction_y,b.correction_y,"correction_y");
  for(int axis=0;axis<2;++axis){
    const auto& x=axis?a.info_y:a.info_x;const auto& y=axis?b.info_y:b.info_x;
    need(x.ts_ms==y.ts_ms&&x.state==y.state&&x.night_id==y.night_id&&x.night_hour==y.night_hour&&x.gate==y.gate&&x.baseline_frozen==y.baseline_frozen&&x.modes_ready==y.modes_ready&&x.modes_from_tonight==y.modes_from_tonight&&x.n_history==y.n_history&&x.n_learn_points==y.n_learn_points&&x.n_frame_learn_valid==y.n_frame_learn_valid&&x.n_corrected==y.n_corrected,"frame info differs");
    for(int j=0;j<3;++j)need(x.v[j]==y.v[j]||(std::isnan(x.v[j])&&std::isnan(y.v[j])),"modal coefficients differ");
  }
}
struct Checkpoint {int64_t requested=0,actual=0;int compared=0;size_t state_bytes=0;};
int run(const char* input,const char* result_path,const char* device){
  std::ofstream report(result_path);
  try{
    std::ifstream in(input,std::ios::binary);need(bool(in),"input open");uint32_t m,n;read_value(in,m);need(m>0&&m<10000,"invalid m");std::vector<std::string> names;
    for(uint32_t j=0;j<m;++j){uint32_t l;read_value(in,l);need(l>0&&l<4096,"invalid name");std::string s(l,' ');in.read(&s[0],l);need(bool(in),"short name");names.push_back(s);}
    read_value(in,n);need(n>0,"empty input");ModalSelfCalConfig cfg;cfg.max_frame_dev=0;
    ModalSelfCalState continuous(cfg);std::string error;need(continuous.Init(device,names,&error,true),error);
    std::unique_ptr<ModalSelfCalState> resumed;std::vector<Checkpoint> checkpoints;
    int active=-1,next=0;uint32_t processed=0;int negative_checks=0;std::string previous_blob;
    for(uint32_t k=0;k<n;++k){
      int64_t ts;read_value(in,ts);std::vector<double>x(m),y(m);in.read(reinterpret_cast<char*>(x.data()),8*m);in.read(reinterpret_cast<char*>(y.data()),8*m);need(bool(in),"short frame");
      if(k==0){
        // Evaluate the second available calendar night after one complete causal
        // learning night. No later observations are used in any checkpoint.
        int64_t day=(ts+8*3600000LL)/86400000LL+1;
        for(int minutes:{22*60+30,23*60+39,26*60+40,31*60+5})checkpoints.push_back({day*86400000LL+int64_t(minutes)*60000LL-8*3600000LL});
      }
      ModalSelfCalResult a;need(continuous.Process(ts,x,y,&a,&error),"continuous "+error);need(a.output_ready,"continuous unpublished");++processed;
      if(resumed){
        ModalSelfCalResult b;need(resumed->Process(ts,x,y,&b,&error),"resumed "+error);compare(a,b);++checkpoints[active].compared;
        if(checkpoints[active].compared==20){resumed.reset();active=-1;}
      }
      if(next<4&&ts>=checkpoints[next].requested){
        need(!resumed,"overlapping checkpoints");auto& cp=checkpoints[next];cp.actual=ts;
        std::string blob;int64_t last;need(continuous.ExportState(&blob,&last,&error),"Export "+error);need(last==ts,"export timestamp");cp.state_bytes=blob.size();
        resumed=std::make_unique<ModalSelfCalState>(cfg);need(resumed->Init(device,names,&error,true),"resume Init "+error);ModalSelfCalResumeInfo info;
        auto corrupt=blob;corrupt[corrupt.size()/2]^=1;need(!resumed->ImportState(corrupt,&info,&error),"corrupt import accepted");++negative_checks;
        need(resumed->ImportState(blob,&info,&error),"valid import after rejection "+error);need(info.last_timestamp_ms==ts,"import timestamp");
        // This malformed-but-checksummed older snapshot reaches component parsing.
        // Its failed import must not replace any part of the current valid state.
        need(!resumed->ImportState(missing_guard(previous_blob.empty()?blob:previous_blob),&info,&error),"missing guard component accepted");++negative_checks;previous_blob=blob;
        auto reverse=names;std::reverse(reverse.begin(),reverse.end());ModalSelfCalState permuted(cfg);need(permuted.Init(device,reverse,&error,true),"permuted Init");need(!permuted.ImportState(blob,&info,&error),"permuted roster accepted");++negative_checks;
        auto different=cfg;different.max_frame_dev=8;ModalSelfCalState mismatch(different);need(mismatch.Init(device,names,&error,true),"mismatch Init");need(!mismatch.ImportState(blob,&info,&error),"config mismatch accepted");++negative_checks;
        different=cfg;different.x_enhancement_gap_min=4.0;ModalSelfCalState gap_mismatch(different);need(gap_mismatch.Init(device,names,&error,true),"gap mismatch Init");need(!gap_mismatch.ImportState(blob,&info,&error),"gap parameter mismatch accepted");++negative_checks;
        different=cfg;different.mount_drift_shrinkage=0.4;ModalSelfCalState mount_mismatch(different);need(mount_mismatch.Init(device,names,&error,true),"mount mismatch Init");need(!mount_mismatch.ImportState(blob,&info,&error),"mount parameter mismatch accepted");++negative_checks;
        different=cfg;different.limit_regression_crossnight_energy=true;ModalSelfCalState history_mismatch(different);need(history_mismatch.Init(device,names,&error,true),"history mismatch Init");need(!history_mismatch.ImportState(blob,&info,&error),"history parameter mismatch accepted");++negative_checks;
        active=next++;
      }
      if(next==4&&!resumed)break;
    }
    need(next==4&&!resumed,"not enough data for all checkpoints");
    report<<"{\n  \"passed\": true,\n  \"device\": \""<<device<<"\",\n  \"markers\": "<<m<<",\n  \"input_frames\": "<<n<<",\n  \"processed_frames\": "<<processed<<",\n  \"negative_import_checks\": "<<negative_checks<<",\n  \"comparison\": \"exact numerical equality, paired NaNs equal; all X/Y outputs, corrections and frame info\",\n  \"checkpoints\": [\n";
    for(size_t i=0;i<checkpoints.size();++i){const auto& c=checkpoints[i];report<<"    {\"requested_timestamp\":"<<c.requested<<",\"actual_timestamp\":"<<c.actual<<",\"compared_frames\":"<<c.compared<<",\"state_bytes\":"<<c.state_bytes<<"}"<<(i+1<checkpoints.size()?",":"")<<'\n';}
    report<<"  ]\n}\n";need(bool(report),"report write");return 0;
  }catch(const std::exception&e){report<<"{\"passed\":false,\"error\":\""<<e.what()<<"\"}\n";std::cerr<<"REAL RESTART FAILURE "<<e.what()<<'\n';return 1;}
}
}
extern "C" __declspec(dllexport) int run_real_restart(const char*input,const char*report,const char*device){return run(input,report,device);}
