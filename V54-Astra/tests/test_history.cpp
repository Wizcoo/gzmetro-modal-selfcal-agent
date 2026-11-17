#include "ModalSelfCal.cpp"
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
int checks=0;
void need(bool ok,const std::string& why){++checks;if(!ok)throw std::runtime_error(why);}
std::vector<std::string> roster(){return {"YD1","YD2","YD3","YD4","YD5","YD6","YD7","YJ1"};}
using AxisImpl=gzmetro_msc::ModalSelfCalAxis::Impl;
AxisImpl::NightStat stat(int day,double bad_coefficient){
    AxisImpl::NightStat h;h.night_id=day;h.names=roster();h.n_frames=240;h.N.assign(64,240);h.S.resize(64);
    double coefficient[8]={1,1,1,1,1,1,bad_coefficient,2};
    for(int i=0;i<8;++i)for(int j=0;j<8;++j)h.S[i*8+j]=240*(0.8*coefficient[i]*coefficient[j]+(i==j?0.2:0.0));
    return h;
}
struct Scenario {double gain=0;bool excluded=false;};
Scenario regression(const std::vector<double>& coefficients,int malformed=0){
    ModalSelfCalConfig raw,guard;raw.K=1;raw.max_frame_dev=0;guard=raw;guard.limit_regression_crossnight_energy=true;
    AxisImpl original,limited;original.cfg=&raw;limited.cfg=&guard;original.SetNames(roster());limited.SetNames(roster());original.NewNight(20);limited.NewNight(20);
    std::vector<double>S(64,0),N(64,0);
    for(size_t k=0;k<coefficients.size();++k){auto h=stat(int(k),coefficients[k]);for(size_t i=0;i<64;++i){S[i]+=h.S[i];N[i]+=h.N[i];}limited.history.push_back(h);}
    if(malformed==1)limited.history.clear();
    if(malformed==2)limited.history[0].S[6*8+6]=std::numeric_limits<double>::quiet_NaN();
    if(malformed==3)for(int i=0;i<6;++i)for(int j=0;j<6;++j)limited.history[0].S[i*8+j]=-240;
    if(malformed==4)for(auto& h:limited.history)for(auto& n:h.N)n=1;
    need(original.ModesFrom(S,N,240*coefficients.size()),"original modes");need(limited.ModesFrom(S,N,240*coefficients.size()),"limited modes");
    need(!original.learn[6]&&!limited.learn[6],"target must exercise excluded regression");
    for(int i=0;i<6;++i)need(original.A[i]==limited.A[i]&&original.learn[i]==limited.learn[i]&&original.use[i]==limited.use[i],"trusted learned row changed");
    need(original.A[7]==limited.A[7]&&limited.use[7]&&!limited.learn[7],"intentional fit_only regression changed");
    return {limited.A[6]/original.A[6],!limited.learn[6]};
}
double range(const std::vector<double>& values){auto mm=std::minmax_element(values.begin(),values.end());return *mm.second-*mm.first;}
void suite(const char* output){
    gzmetro_msc::SetModalSelfCalLogEnabled(false);
    need(regression({5,5,5}).gain==1,"reliable high-amplitude regression should remain full strength");
    need(regression({-0.5,-0.5,20}).gain==0,"polluted regression should be rejected by clean prior nights");
    need(std::abs(regression({1,1,8}).gain-0.6)<1e-12,"continuous energy gain must be 2q");
    need(regression({20}).gain==1,"single-night self-contamination blind spot must remain documented");
    need(regression({5,5,5},1).gain==0,"no history support must fail closed");
    need(regression({5,5,5},2).gain==0,"nonfinite supported energy must fail closed");
    need(regression({5,5,5},3).gain==0,"negative predicted energy must fail closed");
    need(regression({5,5,5},4).gain==0,"insufficient pair coverage must fail closed");
    for(double energy:{0.1,1.0,3.0})for(double cross:{-2.0,-0.5,0.0,0.01,0.25,0.5,1.0,2.0}){
        const double gain=std::clamp(2*cross/energy,0.0,1.0);
        need(gain*gain*energy-2*gain*cross<=1e-12,"historical energy inequality");
    }
    // A real causal multi-night axis stream: one historical night has a large
    // target-only load; the following target trace is quiet while peers move.
    ModalSelfCalConfig original_config;original_config.K=1;original_config.max_frame_dev=0;
    auto limited_config=original_config;limited_config.limit_regression_crossnight_energy=true;
    ModalSelfCalAxis original(original_config),limited(limited_config);original.Bind(roster());limited.Bind(roster());
    const int64_t start=1793592000000LL;std::vector<double> raw_quiet,old_quiet,new_quiet;
    for(int k=0;k<4*1440;++k){
        int day=k/1440,minute=k%1440;double wave=minute>=660&&minute<1140?std::sin((minute-660)/19.0):0.0;
        double c=day==2?10.0:(day==3?0.05:-0.2);std::vector<double>x(8,wave);x[6]=c*wave;x[7]=2*wave;
        auto a=original.Ingest(start+int64_t(k)*60000,x);auto b=limited.Ingest(start+int64_t(k)*60000,x);
        if(day==3&&minute>=680&&minute<1140){raw_quiet.push_back(x[6]);old_quiet.push_back(a[6]);new_quiet.push_back(b[6]);}
    }
    const double raw_range=range(raw_quiet),old_range=range(old_quiet),new_range=range(new_quiet);
    need(old_range>raw_range+1,"quiet historical contamination scenario must be nonvacuous");need(new_range<=raw_range+1e-12,"quiet target must not inherit polluted regression");
    // Public paired API preserves the original V54 W3/enhancement chain even
    // outside the modal window. Check publication and correction accounting.
    ModalSelfCalState public_engine;std::string error;need(public_engine.Init("test",roster(),&error,true),error);
    for(int k=0;k<180;++k){std::vector<double>x(8,std::sin(k)),y(8,std::cos(k));if(k==40)x[2]=std::numeric_limits<double>::quiet_NaN();ModalSelfCalResult r;
        need(public_engine.Process(start+int64_t(k)*60000,x,y,&r,&error),error);need(r.output_ready,"public output");for(int j=0;j<8;++j){need(std::isfinite(x[j])==std::isfinite(r.x[j]),"daytime valid mask");if(std::isfinite(x[j]))need(x[j]-r.x[j]==r.correction_x[j],"correction accounting");}}
    ModalSelfCalState cold;need(cold.Init("cold",roster(),&error,true),error);
    for(int k=0;k<60;++k){std::vector<double>x(8,1.0+std::sin(k)),y(8,2);ModalSelfCalResult r;need(cold.Process(start+int64_t(720+k)*60000,x,y,&r,&error),error);need(r.output_ready&&r.x.size()==x.size(),"cold stream publication");for(int j=0;j<8;++j)need(std::isfinite(r.x[j])&&x[j]-r.x[j]==r.correction_x[j],"cold correction accounting");}
    std::ofstream f(output);f<<"{\n\"passed\":true,\n\"checks\":"<<checks<<",\n\"history_energy_proxy_only\":true,\n\"single_history_blind_spot_tested\":true,\n\"fit_only_unchanged_tested\":true,\n\"quiet_contamination_raw_range_px\":"<<raw_range<<",\n\"quiet_contamination_original_range_px\":"<<old_range<<",\n\"quiet_contamination_final_range_px\":"<<new_range<<"\n}\n";
}
}
extern "C" __declspec(dllexport) int run_tests(const char* path){try{suite(path);return 0;}catch(const std::exception&e){std::ofstream f(path);f<<"{\"passed\":false,\"checks\":"<<checks<<",\"error\":\""<<e.what()<<"\"}\n";return 1;}}
