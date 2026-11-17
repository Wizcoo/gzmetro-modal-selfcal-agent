#include "ModalSelfCal.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>

template<class T> void read_value(std::istream& f,T& v){f.read(reinterpret_cast<char*>(&v),sizeof(v));if(!f)throw std::runtime_error("truncated input");}
template<class T> void write_value(std::ostream& f,const T& v){f.write(reinterpret_cast<const char*>(&v),sizeof(v));}
template<class T> void write_array(std::ostream& f,const std::vector<T>& v){f.write(reinterpret_cast<const char*>(v.data()),sizeof(T)*v.size());}

static ModalSelfCalConfig profile_config(int profile){
    if(profile<0||profile>5)throw std::runtime_error("invalid profile");
    ModalSelfCalConfig cfg; cfg.max_frame_dev=0.0;
    if(profile==1||profile==3||profile==5)cfg.enable_x_w3_filter=false;
    if(profile==2||profile==3||profile==5)cfg.enable_x_velocity_damping=false;
    if(profile==4||profile==5)cfg.enable_x_mount_drift_damping=false;
    return cfg;
}

static void write_config(const std::string& path,int profile,const ModalSelfCalConfig& c){
    std::ofstream f(path);f<<std::setprecision(17)<<std::boolalpha;
    f<<"{\n\"profile_id\":"<<profile<<",\n";
#define NUMBER(x) f<<"\"" #x "\":"<<c.x<<",\n"
    NUMBER(tz_offset_h);NUMBER(ref_start_h);NUMBER(ref_end_h);NUMBER(learn_end_h);NUMBER(apply_end_h);
    NUMBER(ramp_min);NUMBER(cadence_s);NUMBER(K);NUMBER(guard);NUMBER(spread_k);NUMBER(history_nights);
    NUMBER(min_valid_ratio);NUMBER(min_learn_ratio);NUMBER(min_ref_frames);NUMBER(min_valid);
    NUMBER(max_frame_residual);NUMBER(max_frame_dev);NUMBER(enabled);NUMBER(limit_regression_crossnight_energy);
    NUMBER(enable_x_w3_filter);NUMBER(enable_x_mount_drift_damping);NUMBER(mount_drift_shrinkage);
    NUMBER(enable_x_velocity_damping);NUMBER(x_enhancement_gap_min);NUMBER(velocity_damping_tau_min);
#undef NUMBER
    f<<"\"fit_only_prefixes\":[";
    for(size_t i=0;i<c.fit_only_prefixes.size();++i){if(i)f<<',';f<<'"'<<c.fit_only_prefixes[i]<<'"';}
    f<<"],\n\"paired_state_effective_history_energy_x\":true,\n\"paired_state_effective_history_energy_y\":false\n}\n";
    if(!f)throw std::runtime_error("config write failed");
}

static int replay(const char* input,const char* output,const char* status_path,const char* device,int profile){
  try{
    static char logging_buffer[1<<20];std::setvbuf(stderr,logging_buffer,_IOFBF,sizeof(logging_buffer));
    std::ifstream in(input,std::ios::binary);std::ofstream out(output,std::ios::binary),status(status_path);
    if(!in||!out||!status)throw std::runtime_error("cannot open input/output");
    uint32_t m,n;read_value(in,m);if(m==0||m>10000)throw std::runtime_error("invalid roster");
    std::vector<std::string> names;
    for(uint32_t i=0;i<m;++i){uint32_t len;read_value(in,len);if(!len||len>4096)throw std::runtime_error("bad name length");std::string s(len,' ');in.read(&s[0],len);if(!in)throw std::runtime_error("short name");names.push_back(s);}
    read_value(in,n);write_value(out,m);write_value(out,n);
    auto cfg=profile_config(profile);write_config(std::string(output)+".config.json",profile,cfg);
    ModalSelfCalState engine(cfg);std::string error;
    if(!engine.Init(device,names,&error,true))throw std::runtime_error(error);
    status<<"timestamp,state_x,state_y,history_x,history_y,modes_x,modes_y,gate_x,gate_y,corrected_x,corrected_y\n"<<std::setprecision(17);
    std::vector<double> durations;durations.reserve(n);int64_t previous=0;
    for(uint32_t k=0;k<n;++k){
      int64_t ts;read_value(in,ts);if(ts<=previous)throw std::runtime_error("unordered input");previous=ts;
      std::vector<double>x(m),y(m);in.read(reinterpret_cast<char*>(x.data()),8*m);in.read(reinterpret_cast<char*>(y.data()),8*m);
      if(!in)throw std::runtime_error("short frame");ModalSelfCalResult r;
      const auto start=std::chrono::steady_clock::now();
      const bool ok=engine.Process(ts,x,y,&r,&error);
      const auto end=std::chrono::steady_clock::now();
      durations.push_back(std::chrono::duration<double,std::micro>(end-start).count());
      if(!ok||!r.output_ready||r.x.size()!=m||r.y.size()!=m)throw std::runtime_error("Process failed: "+error);
      write_value(out,ts);write_array(out,r.x);write_array(out,r.y);
      status<<ts<<','<<r.info_x.state<<','<<r.info_y.state<<','<<r.info_x.n_history<<','<<r.info_y.n_history<<','<<r.info_x.modes_ready<<','<<r.info_y.modes_ready<<','<<r.info_x.gate<<','<<r.info_y.gate<<','<<r.info_x.n_corrected<<','<<r.info_y.n_corrected<<'\n';
    }
    if(!out||!status||in.peek()!=EOF)throw std::runtime_error("output/trailing input error");
    std::string snapshot;int64_t last;
    if(!engine.ExportState(&snapshot,&last,&error))throw std::runtime_error("state export failed: "+error);
    std::ofstream state(std::string(output)+".state",std::ios::binary);state.write(snapshot.data(),snapshot.size());if(!state)throw std::runtime_error("state write failed");
    const double total=std::accumulate(durations.begin(),durations.end(),0.0);std::sort(durations.begin(),durations.end());
    auto quantile=[&](double q){if(durations.empty())return 0.0;double at=q*(durations.size()-1);size_t i=size_t(at);return durations[i]+(at-i)*(durations[std::min(i+1,durations.size()-1)]-durations[i]);};
    std::ofstream timing(std::string(output)+".timing.json");timing<<std::setprecision(17);
    timing<<"{\"frames\":"<<n<<",\"markers\":"<<m<<",\"process_total_us\":"<<total<<",\"process_p50_us\":"<<quantile(.5)<<",\"process_p95_us\":"<<quantile(.95)<<",\"process_p99_us\":"<<quantile(.99)<<",\"process_max_us\":"<<quantile(1)<<",\"scope\":\"native Process wall time including existing buffered diagnostics; excluding input/output files; not a hard realtime guarantee\"}\n";
    if(!timing)throw std::runtime_error("timing write failed");std::fflush(stderr);
    std::cout<<"OK profile="<<profile<<" device="<<device<<" frames="<<n<<" markers="<<m<<'\n';return 0;
  }catch(const std::exception&e){std::cerr<<"REPLAY ERROR: "<<e.what()<<'\n';std::fflush(stderr);return 1;}
}

extern "C" __declspec(dllexport) int replay_profile(const char* input,const char* output,const char* status,const char* device,int profile){return replay(input,output,status,device,profile);}
int main(int argc,char**argv){if(argc!=6){std::cerr<<"input output status device profile_id\n";return 2;}return replay(argv[1],argv[2],argv[3],argv[4],std::stoi(argv[5]));}
