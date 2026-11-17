#include <cstring>

static void window_require(bool condition,const std::string& message){
    if(!condition)throw std::runtime_error(message);
}
static bool vector_bits_equal(const std::vector<double>& a,const std::vector<double>& b){
    return a.size()==b.size() && std::memcmp(a.data(),b.data(),a.size()*sizeof(double))==0;
}
static void require_same_result(const ModalSelfCalResult& a,const ModalSelfCalResult& b){
    window_require(vector_bits_equal(a.x,b.x)&&vector_bits_equal(a.y,b.y),"restart output differs");
    window_require(a.info_x.gate==b.info_x.gate&&a.info_y.gate==b.info_y.gate&&
                   a.info_x.state==b.info_x.state&&a.info_y.state==b.info_y.state,"restart state/gate differs");
}

static void check_real_restart(const char* input,const char* report,const char* device,int profile){
    std::ifstream in(input,std::ios::binary);window_require(bool(in),"missing restart input");
    uint32_t m,n;read_value(in,m);std::vector<std::string> names;
    for(uint32_t j=0;j<m;++j){uint32_t len;read_value(in,len);std::string name(len,' ');in.read(&name[0],len);names.push_back(name);}
    read_value(in,n);
    auto cfg=profile_config(profile);std::string error;
    ModalSelfCalState uninterrupted(cfg);window_require(uninterrupted.Init(device,names,&error,true),error);
    std::unique_ptr<ModalSelfCalState> restarted;int64_t resume_ts=0;uint32_t compared=0,boundary_frames=0;
    for(uint32_t k=0;k<n;++k){
        int64_t ts;read_value(in,ts);std::vector<double>x(m),y(m);
        in.read(reinterpret_cast<char*>(x.data()),m*sizeof(double));in.read(reinterpret_cast<char*>(y.data()),m*sizeof(double));
        window_require(bool(in),"short restart input");ModalSelfCalResult expected;
        window_require(uninterrupted.Process(ts,x,y,&expected,&error),error);
        if(restarted){
            ModalSelfCalResult actual;window_require(restarted->Process(ts,x,y,&actual,&error),error);
            require_same_result(expected,actual);++compared;
            double local=std::fmod(double(ts)/3600000.0+8.0,24.0);
            if(local>=8.0 && local<=8.0+20.0/60.0)++boundary_frames;
        }
        if(k==n/2){
            std::string snapshot;window_require(uninterrupted.ExportState(&snapshot,&resume_ts,&error),error);
            restarted=std::make_unique<ModalSelfCalState>(cfg);
            window_require(restarted->Init(device,names,&error,false),error);
            ModalSelfCalResumeInfo resume;window_require(restarted->ImportState(snapshot,&resume,&error),error);
            window_require(resume.last_timestamp_ms==ts,"wrong resume timestamp");
            for(int mismatch=0;mismatch<3;++mismatch){
                auto other=cfg;
                if(mismatch==0)other.x_apply_end_h=0;
                if(mismatch==1)other.x_apply_end_h=31;
                if(mismatch==2)other.fade_x_enhancements_with_gate=!cfg.fade_x_enhancements_with_gate;
                ModalSelfCalState rejected(other);window_require(rejected.Init(device,names,&error,false),error);
                window_require(!rejected.ImportState(snapshot,&resume,&error),"config mismatch accepted");
                window_require(error=="saved math parameters differ","unexpected mismatch rejection: "+error);
            }
        }
    }
    window_require(compared>0&&boundary_frames>0,"restart did not cover 08 exit boundary");
    const double bad[]={-1.0,cfg.learn_end_h-0.01,36.01,std::numeric_limits<double>::quiet_NaN(),std::numeric_limits<double>::infinity()};
    for(double value:bad){auto test=cfg;test.x_apply_end_h=value;ModalSelfCalState rejected(test);window_require(!rejected.Init(device,names,&error,true),"invalid end hour accepted");}
    for(int boundary=0;boundary<3;++boundary){
        auto test=cfg;test.ramp_min=20.0;
        if(boundary==0)test.x_apply_end_h=36.0;
        if(boundary==1)test.x_apply_end_h=35.9;
        if(boundary==2){test.x_apply_end_h=0.0;test.apply_end_h=36.0;test.fade_x_enhancements_with_gate=true;}
        ModalSelfCalState rejected(test);window_require(!rejected.Init(device,names,&error,true),"X ramp across noon accepted");
        window_require(error=="X exit ramp crosses local noon","unexpected noon rejection: "+error);
    }
    for(double value:{0.0,cfg.learn_end_h,35.5}){auto test=cfg;test.x_apply_end_h=value;ModalSelfCalState accepted(test);window_require(accepted.Init(device,names,&error,true),error);}
    {auto test=cfg;test.x_apply_end_h=36.0;test.ramp_min=0.0;ModalSelfCalState accepted(test);window_require(accepted.Init(device,names,&error,true),error);}
    {auto test=cfg;test.x_apply_end_h=0.0;test.fade_x_enhancements_with_gate=false;test.apply_end_h=36.0;test.ramp_min=20.0;ModalSelfCalState accepted(test);window_require(accepted.Init(device,names,&error,true),error);}
    std::ofstream out(report);out<<"{\"profile_id\":"<<profile<<",\"input_frames\":"<<n<<",\"restart_compared_frames\":"<<compared
       <<",\"post0800_through0820_compared_frames\":"<<boundary_frames<<",\"resume_timestamp_ms\":"<<resume_ts
       <<",\"x_y_restart_bitwise_equal\":true,\"gate_and_state_equal\":true,\"mismatched_end_0_and_31_rejected\":true,\"mismatched_fade_rejected\":true,\"invalid_end_hour_cases_rejected\":8,\"valid_end_hour_cases_accepted\":5,\"new_x_features_noon_ramp_guard\":true,\"legacy_disabled_configuration_range_preserved\":true}\n";
    window_require(bool(out),"restart report write failed");
}

static void check_synthetic_fade(const std::string& prefix,bool step){
    std::vector<std::string> names;for(int j=0;j<8;++j)names.push_back("TEST"+std::to_string(j));
    ModalSelfCalConfig cfg;cfg.max_frame_dev=0;cfg.min_valid=1000;
    auto fading_cfg=cfg;fading_cfg.fade_x_enhancements_with_gate=true;
    auto extended_cfg=cfg;extended_cfg.x_apply_end_h=32;
    auto core_cfg=cfg;core_cfg.enable_x_mount_drift_damping=false;core_cfg.enable_x_velocity_damping=false;
    ModalSelfCalState old(cfg),fading(fading_cfg),extended(extended_cfg),core(core_cfg);
    std::string error;
    for(auto* state:{&old,&fading,&extended,&core})window_require(state->Init("synthetic-boundary",names,&error,true),error);
    std::unique_ptr<ModalSelfCalState> restarted;
    std::ofstream csv(prefix+(step?"_step.csv":"_static.csv"));
    csv<<"minute_from_2200,raw_x,core_x,old_x,fade_x,extended_x,gate\n"<<std::setprecision(17);
    double previous_old=0,previous_fade=0,old_drop=0,fade_drop=0,max_error=0;
    int fade_frames=0,restart_frames=0;
    for(int k=0;k<=565;++k){
        int64_t ts=20000LL*86400000+14LL*3600000+k*60000LL;
        double drift=(std::max)(0.0,(std::min)(4.0,(k-60)*4.0/420.0));
        if(step&&k>=541)drift+=1.0;
        std::vector<double>x(8),y(8);for(int j=0;j<8;++j){x[j]=100+10*j+drift;y[j]=200+5*j;}
        ModalSelfCalResult ro,rf,re,rc;
        window_require(old.Process(ts,x,y,&ro,&error),error);window_require(fading.Process(ts,x,y,&rf,&error),error);
        window_require(extended.Process(ts,x,y,&re,&error),error);window_require(core.Process(ts,x,y,&rc,&error),error);
        const double g=rf.info_x.gate;
        if(k>=540&&k<=560&&g>0){
            ++fade_frames;
            for(size_t j=0;j<x.size();++j){
                double expected=rc.x[j]+g*(re.x[j]-rc.x[j]);
                max_error=(std::max)(max_error,std::abs(expected-rf.x[j]));
                window_require(std::abs(expected-rf.x[j])<1e-12,"fade formula differs on synthetic input");
            }
        }
        if(k<=540)window_require(vector_bits_equal(ro.x,rf.x),"fade changed entry/full-gate output");
        if(k>=561)window_require(vector_bits_equal(rc.x,rf.x),"fade not passthrough after exit");
        window_require(vector_bits_equal(ro.y,rf.y),"synthetic Y changed");
        if(k==541){old_drop=ro.x[0]-previous_old;fade_drop=rf.x[0]-previous_fade;}
        if(restarted){ModalSelfCalResult restored;window_require(restarted->Process(ts,x,y,&restored,&error),error);require_same_result(rf,restored);++restart_frames;}
        if(k==545){
            std::string snapshot;int64_t last;window_require(fading.ExportState(&snapshot,&last,&error),error);
            restarted=std::make_unique<ModalSelfCalState>(fading_cfg);window_require(restarted->Init("synthetic-boundary",names,&error,false),error);
            ModalSelfCalResumeInfo resume;window_require(restarted->ImportState(snapshot,&resume,&error),error);
        }
        if(k>=530)csv<<k<<','<<x[0]<<','<<rc.x[0]<<','<<ro.x[0]<<','<<rf.x[0]<<','<<re.x[0]<<','<<g<<'\n';
        previous_old=ro.x[0];previous_fade=rf.x[0];
    }
    window_require(fade_frames>10&&restart_frames==20,"synthetic coverage incomplete");
    if(!step)window_require(std::abs(old_drop)>1.0&&std::abs(fade_drop)<0.2,"static boundary drop did not improve");
    std::ofstream out(prefix+(step?"_step.json":"_static.json"));out<<std::setprecision(17)
      <<"{\"kind\":\""<<(step?"step":"static plateau")<<"\",\"configuration_note\":\"min_valid=1000 isolates the enhancement gate with native core outputs; not a physical accuracy test\",\"fade_formula_max_abs_error\":"<<max_error
      <<",\"old_0701_change_px\":"<<old_drop<<",\"fade_0701_change_px\":"<<fade_drop
      <<",\"fade_formula_checked_frames\":"<<fade_frames<<",\"restart_during_fade_compared_frames\":"<<restart_frames
      <<",\"restart_xy_bitwise_equal\":true,\"entry_and_full_gate_unchanged\":true,\"post_exit_matches_core\":true,\"y_bitwise_equal\":true}\n";
    window_require(bool(out)&&bool(csv),"synthetic report write failed");
}

extern "C" __declspec(dllexport) int window_native_checks(const char* input,const char* prefix,const char* device){
    try{
        static char logging_buffer[1<<20];std::setvbuf(stderr,logging_buffer,_IOFBF,sizeof(logging_buffer));
        check_real_restart(input,(std::string(prefix)+"_restart_end08.json").c_str(),device,11);
        check_real_restart(input,(std::string(prefix)+"_restart_fade08.json").c_str(),device,15);
        check_synthetic_fade(std::string(prefix)+"_boundary",false);
        check_synthetic_fade(std::string(prefix)+"_boundary",true);
        std::fflush(stderr);return 0;
    }catch(const std::exception& error){std::cerr<<"WINDOW CHECK ERROR: "<<error.what()<<'\n';std::fflush(stderr);return 1;}
}
