#include "ModalSelfCal.h"
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <cstdio>

template<class T> void read_value(std::istream& f,T& v){f.read(reinterpret_cast<char*>(&v),sizeof(v));if(!f)throw std::runtime_error("truncated input");}
template<class T> void write_value(std::ostream& f,const T& v){f.write(reinterpret_cast<const char*>(&v),sizeof(v));}
template<class T> void write_array(std::ostream& f,const std::vector<T>& v){f.write(reinterpret_cast<const char*>(v.data()),sizeof(T)*v.size());}

static int replay(const char* input,const char* output,const char* status_path,const char* device,double max_frame_dev) {
  try {
    // Buffer legacy frame diagnostics; this changes I/O only, never computation.
    static char diagnostic_buffer[1 << 20];
    std::setvbuf(stderr,diagnostic_buffer,_IOFBF,sizeof(diagnostic_buffer));
    std::ifstream in(input,std::ios::binary);
    std::ofstream out(output,std::ios::binary),status(status_path);
    if(!in||!out||!status)throw std::runtime_error("cannot open replay files");
    uint32_t m,n;read_value(in,m);if(m==0||m>10000)throw std::runtime_error("invalid roster size");
    std::vector<std::string> names;
    for(uint32_t j=0;j<m;++j){uint32_t l;read_value(in,l);if(!l||l>4096)throw std::runtime_error("invalid name size");std::string s(l,' ');in.read(&s[0],l);if(!in)throw std::runtime_error("short name");names.push_back(s);}
    read_value(in,n);write_value(out,m);write_value(out,n);
#ifdef ASTRA
    std::ofstream diagnostic(std::string(output)+".diagnostic.bin",std::ios::binary);
    if(!diagnostic)throw std::runtime_error("cannot open diagnostics");
    write_value(diagnostic,m);write_value(diagnostic,n);
#endif
    ModalSelfCalConfig cfg;cfg.max_frame_dev=max_frame_dev;
    ModalSelfCalState engine(cfg);std::string error;
    if(!engine.Init(device,names,&error,true))throw std::runtime_error(error);
    status<<"timestamp,state_x,state_y,history_x,history_y,modes_x,modes_y,gate_x,gate_y,corrected_x,corrected_y\n"<<std::setprecision(17);
    int64_t prior=0;
    for(uint32_t k=0;k<n;++k){
      int64_t ts;read_value(in,ts);if(ts<=prior)throw std::runtime_error("input not strictly increasing");prior=ts;
      std::vector<double>x(m),y(m);in.read(reinterpret_cast<char*>(x.data()),8*m);in.read(reinterpret_cast<char*>(y.data()),8*m);
      if(!in)throw std::runtime_error("short frame");ModalSelfCalResult r;
      if(!engine.Process(ts,x,y,&r,&error)||!r.output_ready||r.x.size()!=m||r.y.size()!=m)throw std::runtime_error("process failed: "+error);
      write_value(out,ts);write_array(out,r.x);write_array(out,r.y);
      status<<ts<<','<<r.info_x.state<<','<<r.info_y.state<<','<<r.info_x.n_history<<','<<r.info_y.n_history<<','<<r.info_x.modes_ready<<','<<r.info_y.modes_ready<<','<<r.info_x.gate<<','<<r.info_y.gate<<','<<r.info_x.n_corrected<<','<<r.info_y.n_corrected<<'\n';
#ifdef ASTRA
      if(r.x_proposed.size()!=m||r.x_guard_baseline.size()!=m||r.x_guard_budget.size()!=m||r.x_guard_flags.size()!=m)throw std::runtime_error("wrong diagnostic sizes");
      write_value(diagnostic,ts);write_array(diagnostic,r.x_guard_baseline);write_array(diagnostic,r.x_guard_budget);write_array(diagnostic,r.x_proposed);write_array(diagnostic,r.x_guard_flags);
#endif
    }
    if(!out||!status||in.peek()!=EOF)throw std::runtime_error("output failed or trailing input");
#ifdef ASTRA
    if(!diagnostic)throw std::runtime_error("diagnostic output failed");
#endif
    std::string snapshot;int64_t last;
    if(!engine.ExportState(&snapshot,&last,&error))throw std::runtime_error("state export: "+error);
    std::ofstream state(std::string(output)+".state",std::ios::binary);state.write(snapshot.data(),snapshot.size());if(!state)throw std::runtime_error("state write failed");
    std::cout<<"OK device="<<device<<" frames="<<n<<" markers="<<m<<" last="<<last<<'\n';return 0;
  } catch(const std::exception& e){std::cerr<<"REPLAY ERROR: "<<e.what()<<'\n';return 1;}
}

extern "C" __declspec(dllexport) int replay_files(const char* input,const char* output,const char* status,const char* device,double max_frame_dev){return replay(input,output,status,device,max_frame_dev);}
int main(int argc,char**argv){if(argc<5||argc>6){std::cerr<<"input output status device [max_frame_dev]\n";return 2;}return replay(argv[1],argv[2],argv[3],argv[4],argc==6?std::stod(argv[5]):0.0);}
