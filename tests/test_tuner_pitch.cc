#include "../native/tuner_pitch.h"
#include <cmath>
#include <iostream>

int main() {
  constexpr double pi = 3.14159265358979323846;
  std::vector<float> samples(2048, 0);
  if (EstimateTunerPitch(samples) != 0) return 1;
  for (double expected : {82.4069, 110.0, 220.0, 440.0, 880.0}) {
    for (size_t i = 0; i < samples.size(); ++i)
      samples[i] = static_cast<float>(0.3 * std::sin(2 * pi * expected * i / 11025));
    const double actual = EstimateTunerPitch(samples);
    const double cents = 1200 * std::log2(actual / expected);
    if (!std::isfinite(cents) || std::abs(cents) > 3) {
      std::cerr << expected << " Hz: " << actual << " Hz, " << cents << " cents\n";
      return 1;
    }
  }
  return 0;
}
