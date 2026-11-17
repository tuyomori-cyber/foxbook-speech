// Standalone comparison diagnostic for voicute's Japanese "mirai" model.
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <vector>
#include "onnxruntime_c_api.h"
#include "tuner_pitch.h"

namespace {
constexpr size_t kWindow = 16080, kHop = 640, kFrames = 98, kMels = 32;
volatile std::sig_atomic_t running = 1;
void stop(int) { running = 0; }
struct Runtime {
  void* library{}; const OrtApi* api{}; OrtEnv* env{}; OrtSessionOptions* options{};
  OrtMemoryInfo* memory{}; OrtSession *mel{}, *model{};
  void check(OrtStatus* status) { if (status) { std::string message = api->GetErrorMessage(status); api->ReleaseStatus(status); throw std::runtime_error(message); } }
  Runtime(const std::string& lib, const std::string& mel_path, const std::string& model_path) {
    library = dlopen(lib.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (!library) throw std::runtime_error(dlerror());
    auto get = reinterpret_cast<const OrtApiBase* (ORT_API_CALL*)()>(dlsym(library, "OrtGetApiBase"));
    if (!get || !(api = get()->GetApi(ORT_API_VERSION))) throw std::runtime_error("ONNX Runtime APIのバージョンが一致しません");
    check(api->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "mirai", &env));
    check(api->CreateSessionOptions(&options));
    check(api->SetIntraOpNumThreads(options, 1));
    check(api->SetInterOpNumThreads(options, 1));
    check(api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &memory));
    check(api->CreateSession(env, mel_path.c_str(), options, &mel));
    check(api->CreateSession(env, model_path.c_str(), options, &model));
  }
  ~Runtime() { if (model) api->ReleaseSession(model); if (mel) api->ReleaseSession(mel); if (memory) api->ReleaseMemoryInfo(memory); if (options) api->ReleaseSessionOptions(options); if (env) api->ReleaseEnv(env); if (library) dlclose(library); }
  OrtValue* run(OrtSession* session, float* data, size_t size, const int64_t* shape, size_t dims) {
    OrtValue *input{}, *output{};
    check(api->CreateTensorWithDataAsOrtValue(memory, data, size * sizeof(float), shape, dims, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &input));
    const char* in[] = {"input"};
    OrtAllocator* allocator{}; char* output_name{};
    check(api->GetAllocatorWithDefaultOptions(&allocator));
    check(api->SessionGetOutputName(session, 0, allocator, &output_name));
    const char* out[] = {output_name};
    OrtStatus* status = api->Run(session, nullptr, in, const_cast<const OrtValue* const*>(&input), 1, out, 1, &output);
    allocator->Free(allocator, output_name); api->ReleaseValue(input); check(status); return output;
  }
  float predict(std::vector<float>& audio) {
    int64_t shape[] = {1, static_cast<int64_t>(kWindow)};
    OrtValue* features = run(mel, audio.data(), audio.size(), shape, 2);
    OrtTensorTypeAndShapeInfo* info{}; check(api->GetTensorTypeAndShape(features, &info));
    size_t count{}; check(api->GetTensorShapeElementCount(info, &count));
    size_t nd{}; check(api->GetDimensionsCount(info, &nd));
    std::vector<int64_t> dims(nd); check(api->GetDimensions(info, dims.data(), nd)); api->ReleaseTensorTypeAndShapeInfo(info);
    if (nd != 4 || dims[0] != 1 || dims[1] != 1 || dims[2] < static_cast<int64_t>(kFrames) || dims[3] != static_cast<int64_t>(kMels) || count < kFrames*kMels) { api->ReleaseValue(features); throw std::runtime_error("メル特徴量の形状が想定と異なります"); }
    float* values{}; check(api->GetTensorMutableData(features, reinterpret_cast<void**>(&values)));
    std::vector<float> input(kFrames*kMels); size_t start = (static_cast<size_t>(dims[2])-kFrames)*kMels;
    for (size_t i=0; i<input.size(); ++i) input[i] = values[start+i]/10.0F+2.0F;
    api->ReleaseValue(features);
    int64_t model_shape[] = {1, kFrames, kMels};
    OrtValue* prediction = run(model, input.data(), input.size(), model_shape, 3);
    OrtTensorTypeAndShapeInfo* prediction_info{}; check(api->GetTensorTypeAndShape(prediction, &prediction_info));
    size_t output_count{}; check(api->GetTensorShapeElementCount(prediction_info, &output_count)); api->ReleaseTensorTypeAndShapeInfo(prediction_info);
    if (output_count != 1) { api->ReleaseValue(prediction); throw std::runtime_error("みらいモデルの出力形状が想定と異なります"); }
    float* score{}; check(api->GetTensorMutableData(prediction, reinterpret_cast<void**>(&score)));
    // For one keyword, upstream sigmoid-to-softmax conversion equals p.
    float result = std::clamp(*score, 1e-6F, 1.0F-1e-6F); api->ReleaseValue(prediction); return result;
  }
};
double cpu() { rusage u{}; getrusage(RUSAGE_SELF, &u); return u.ru_utime.tv_sec+u.ru_stime.tv_sec+(u.ru_utime.tv_usec+u.ru_stime.tv_usec)/1e6; }
long rss() { std::ifstream f("/proc/self/status"); std::string line; while (std::getline(f,line)) { long v; if (std::sscanf(line.c_str(),"VmRSS: %ld kB",&v)==1) return v; } return -1; }
}
int main(int argc, char** argv) {
 try {
  std::string lib, mel, model, raw; float threshold=0.5F; int report=10; bool tuner=false;
  for (int i=1;i<argc;++i) { std::string a=argv[i]; auto value=[&]() { if (++i>=argc) throw std::runtime_error("引数の値がありません: "+a); return std::string(argv[i]); };
    if(a=="--runtime") lib=value(); else if(a=="--mel") mel=value(); else if(a=="--model") model=value(); else if(a=="--raw") raw=value(); else if(a=="--threshold") threshold=std::stof(value()); else if(a=="--report-every") report=std::stoi(value()); else if(a=="--tuner") tuner=true; else if(a=="--help") { std::cout << "--runtime LIB --mel MODEL --model MODEL [--raw PCM16LE] [--tuner] [--threshold 0..1] [--report-every SEC]\n"; return 0; } else throw std::runtime_error("不明な引数: "+a);
  }
  if(lib.empty()||mel.empty()||model.empty()||!std::isfinite(threshold)||threshold<0||threshold>1||report<0) throw std::runtime_error("--runtime、--mel、--modelと有効な閾値を指定してください");
  Runtime rt(lib,mel,model);
  FILE* input = raw.empty()? popen("arecord -q -f S16_LE -r 16000 -c 1 -t raw", "r") : std::fopen(raw.c_str(),"rb");
  if(!input) throw std::runtime_error("音声入力を開けません");
  std::signal(SIGINT,stop); std::signal(SIGTERM,stop);
  std::cout << "みらいの単独診断: 閾値 " << threshold << " / L1 2回 / L3 1.5秒。Ctrl+Cで終了。音声は保存しません。\n" << std::flush;
  std::vector<float> audio; audio.reserve(kWindow+kHop); std::array<unsigned char,kHop*2> bytes{}; int consecutive=0,gap=0; bool triggered=false; size_t pitch_hop=0;
  auto last=std::chrono::steady_clock::now(), last_trigger=last; double last_cpu=cpu();
  while(running) {
    size_t n=std::fread(bytes.data(),1,bytes.size(),input); if(!n) break; if(n%2) throw std::runtime_error("PCMデータが不完全です");
    for(size_t i=0;i<n;i+=2) { int value=bytes[i] | (static_cast<int>(bytes[i+1])<<8); if(value>=32768) value-=65536; audio.push_back(static_cast<float>(value)); }
    pitch_hop += n/2;
    if(tuner && audio.size()>=2048 && pitch_hop>=1600) {
      std::vector<float> pitch(audio.end()-2048,audio.end());
      for (float& sample : pitch) sample /= 32768.0F;
      std::cout << "PITCH: " << EstimateTunerPitch(pitch,16000) << "\n" << std::flush;
      pitch_hop=0;
    }
    if(audio.size()>=kWindow) {
      std::vector<float> window(audio.end()-kWindow,audio.end()); float score=rt.predict(window); auto now=std::chrono::steady_clock::now();
      if(!raw.empty()) std::cout << "score: " << score << "\n";
      if(score>threshold) { ++consecutive; gap=0; } else if(consecutive>0 && ++gap>2) { consecutive=0; gap=0; }
      if(score>threshold && consecutive>=2 && (!triggered || now-last_trigger>=std::chrono::milliseconds(1500))) { std::cout << "検出: みらい (score=" << score << ")\n" << std::flush; consecutive=0; triggered=true; last_trigger=now; }
      audio.erase(audio.begin(),audio.end()-kWindow);
    }
    auto now=std::chrono::steady_clock::now(); double elapsed=std::chrono::duration<double>(now-last).count();
    if(report && elapsed>=report) { double c=cpu(); std::cout << "負荷: CPU " << (c-last_cpu)/elapsed*100 << "% / RSS " << rss() << " KiB\n" << std::flush; last=now; last_cpu=c; }
  }
  if(raw.empty()) pclose(input); else std::fclose(input); return 0;
 } catch(const std::exception& e) { std::cerr << "エラー: " << e.what() << '\n'; return 1; }
}
