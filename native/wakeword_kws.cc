// Standalone native sherpa-onnx wakeword diagnostic. This is deliberately
// separate from the foxbook-speech service: it does not save audio or start a
// recording/recognition request after detecting FOX.
#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <sys/resource.h>
#include <unistd.h>
#include <vector>

#include "sherpa-onnx/c-api/c-api.h"

namespace {

constexpr std::string_view kStem = "epoch-12-avg-2-chunk-16-left-64";
constexpr std::string_view kFoxKeyword = "▁F O X @FOX\n";
volatile std::sig_atomic_t g_running = 1;

struct Options {
  std::filesystem::path model_dir;
  std::string device = "default";
  float threshold = 0.25F;
  int report_every = 10;
  bool show_level = false;
};

void OnSignal(int) { g_running = 0; }

[[noreturn]] void Usage(const char *program, const std::string &error = {}) {
  if (!error.empty()) std::cerr << "エラー: " << error << "\n\n";
  std::cerr << "使用法: " << program << " --model-dir PATH [options]\n"
            << "  --device NAME          ALSA入力（既定: default）\n"
            << "  --threshold 0..1      検出閾値（既定: 0.25）\n"
            << "  --report-every SEC    CPU/RSS表示間隔。0で非表示（既定: 10）\n"
            << "  --show-level          左右の入力ピークを表示\n";
  std::exit(error.empty() ? 0 : 2);
}

Options ParseOptions(int argc, char **argv) {
  Options options;
  for (int index = 1; index < argc; ++index) {
    const std::string argument = argv[index];
    const auto value = [&]() -> std::string {
      if (++index == argc) Usage(argv[0], argument + " には値が必要です");
      return argv[index];
    };
    if (argument == "--model-dir") options.model_dir = value();
    else if (argument == "--device") options.device = value();
    else if (argument == "--threshold") options.threshold = std::stof(value());
    else if (argument == "--report-every") options.report_every = std::stoi(value());
    else if (argument == "--show-level") options.show_level = true;
    else if (argument == "--help" || argument == "-h") Usage(argv[0]);
    else Usage(argv[0], "不明な引数: " + argument);
  }
  if (options.model_dir.empty()) Usage(argv[0], "--model-dir を指定してください");
  if (options.threshold < 0 || options.threshold > 1) Usage(argv[0], "--thresholdは0〜1です");
  if (options.report_every < 0) Usage(argv[0], "--report-everyは0以上です");
  return options;
}

double ProcessSeconds() {
  rusage usage{};
  getrusage(RUSAGE_SELF, &usage);
  return usage.ru_utime.tv_sec + usage.ru_stime.tv_sec +
         (usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) / 1'000'000.0;
}

long RssKiB() {
  FILE *status = std::fopen("/proc/self/status", "r");
  if (!status) return -1;
  std::array<char, 256> line{};
  long result = -1;
  while (std::fgets(line.data(), line.size(), status)) {
    if (std::sscanf(line.data(), "VmRSS: %ld kB", &result) == 1) break;
  }
  std::fclose(status);
  return result;
}

void CheckModelFiles(const std::filesystem::path &model) {
  const std::array<std::filesystem::path, 4> files = {
      model / "tokens.txt", model / ("encoder-" + std::string(kStem) + ".int8.onnx"),
      model / ("decoder-" + std::string(kStem) + ".int8.onnx"),
      model / ("joiner-" + std::string(kStem) + ".int8.onnx")};
  for (const auto &file : files) {
    if (!std::filesystem::is_regular_file(file)) {
      throw std::runtime_error("必要なモデルファイルがありません: " + file.string());
    }
  }
}

bool IsSafeAlsaDevice(const std::string &device) {
  return !device.empty() && std::all_of(device.begin(), device.end(), [](unsigned char ch) {
    return std::isalnum(ch) || ch == '_' || ch == ':' || ch == ',' || ch == '.' || ch == '-';
  });
}

}  // namespace

int main(int argc, char **argv) {
  try {
    const Options options = ParseOptions(argc, argv);
    CheckModelFiles(options.model_dir);
    if (!IsSafeAlsaDevice(options.device)) {
      throw std::runtime_error("ALSAデバイス名に使えない文字があります");
    }

    // Use the stable C ABI exposed by the same wheel that the Python
    // diagnostic uses. The C++ convenience wrapper is intentionally avoided:
    // its STL ABI is not guaranteed to match the system compiler.
    const auto tokens = (options.model_dir / "tokens.txt").string();
    const auto encoder = (options.model_dir / ("encoder-" + std::string(kStem) + ".int8.onnx")).string();
    const auto decoder = (options.model_dir / ("decoder-" + std::string(kStem) + ".int8.onnx")).string();
    const auto joiner = (options.model_dir / ("joiner-" + std::string(kStem) + ".int8.onnx")).string();
    SherpaOnnxKeywordSpotterConfig config{};
    config.feat_config.sample_rate = 16000;
    config.feat_config.feature_dim = 80;
    config.model_config.tokens = tokens.c_str();
    config.model_config.transducer.encoder = encoder.c_str();
    config.model_config.transducer.decoder = decoder.c_str();
    config.model_config.transducer.joiner = joiner.c_str();
    config.model_config.num_threads = 1;
    config.model_config.provider = "cpu";
    config.keywords_buf = kFoxKeyword.data();
    config.keywords_threshold = options.threshold;
    config.keywords_buf_size = static_cast<int32_t>(kFoxKeyword.size());
    const auto *spotter = SherpaOnnxCreateKeywordSpotter(&config);
    if (!spotter) throw std::runtime_error("sherpa-onnx検出器を初期化できません");
    const auto *stream = SherpaOnnxCreateKeywordStream(spotter);
    if (!stream) {
      SherpaOnnxDestroyKeywordSpotter(spotter);
      throw std::runtime_error("sherpa-onnx入力ストリームを作成できません");
    }

    const std::string command = "arecord -q -D " + options.device + " -f cd -t raw -";
    FILE *input = popen(command.c_str(), "r");
    if (!input) throw std::runtime_error("arecordを起動できません");
    std::signal(SIGINT, OnSignal);
    std::signal(SIGTERM, OnSignal);
    std::cout << "FOX のネイティブ検出を準備中。音声は保存しません。終了は Ctrl+C。\n"
              << "マイク入力を受信中。話してください。\n" << std::flush;

    std::array<int16_t, 4096> pcm{};
    std::vector<float> left;
    left.reserve(pcm.size() / 2);
    auto last_report = std::chrono::steady_clock::now();
    auto last_cpu = ProcessSeconds();
    auto next_level = last_report + std::chrono::seconds(2);
    float left_peak = 0;
    float right_peak = 0;
    while (g_running) {
      const size_t count = std::fread(pcm.data(), sizeof(int16_t), pcm.size(), input);
      if (count == 0) break;
      if (count % 2 != 0) throw std::runtime_error("録音データが不完全です");
      left.clear();
      for (size_t index = 0; index < count; index += 2) {
        left.push_back(pcm[index] / 32768.0F);
        if (options.show_level) {
          left_peak = std::max(left_peak, std::abs(left.back()));
          right_peak = std::max(right_peak, std::abs(pcm[index + 1] / 32768.0F));
        }
      }
      SherpaOnnxOnlineStreamAcceptWaveform(stream, 44100, left.data(), static_cast<int32_t>(left.size()));
      while (SherpaOnnxIsKeywordStreamReady(spotter, stream)) {
        SherpaOnnxDecodeKeywordStream(spotter, stream);
        const auto *result = SherpaOnnxGetKeywordResult(spotter, stream);
        if (result && result->keyword && result->keyword[0] != '\0') {
          std::cout << "検出: " << result->keyword << "\n" << std::flush;
          SherpaOnnxResetKeywordStream(spotter, stream);
        }
        SherpaOnnxDestroyKeywordResult(result);
      }
      const auto now = std::chrono::steady_clock::now();
      if (options.show_level && now >= next_level) {
        std::cout << "入力ピーク: 左（検出に使用）" << left_peak * 100
                  << "% / 右 " << right_peak * 100 << "%\n" << std::flush;
        left_peak = right_peak = 0;
        next_level = now + std::chrono::seconds(2);
      }
      const auto elapsed = std::chrono::duration<double>(now - last_report).count();
      if (options.report_every > 0 && elapsed >= options.report_every) {
        const double current_cpu = ProcessSeconds();
        std::cout << "負荷: CPU " << (current_cpu - last_cpu) / elapsed * 100.0
                  << "% / RSS " << RssKiB() << " KiB";
        std::cout << "\n" << std::flush;
        last_report = now;
        last_cpu = current_cpu;
      }
    }
    pclose(input);
    SherpaOnnxDestroyOnlineStream(stream);
    SherpaOnnxDestroyKeywordSpotter(spotter);
    return g_running ? 1 : 130;
  } catch (const std::exception &error) {
    std::cerr << "ウェイクワード診断に失敗しました: " << error.what() << "\n";
    return 1;
  }
}
