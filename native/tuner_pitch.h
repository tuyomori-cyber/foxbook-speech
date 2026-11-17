#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

// YIN difference function on 11025 Hz mono samples. Returns 0 for silence
// or an unreliable estimate. The caller supplies a fixed 2048-sample window.
inline double EstimateTunerPitch(const std::vector<float>& samples, int sample_rate = 11025) {
  constexpr double kMinFrequency = 55.0;
  constexpr double kMaxFrequency = 1200.0;
  constexpr double kThreshold = 0.15;
  if (samples.size() < 2048) return 0;
  double mean = 0;
  for (float sample : samples) mean += sample;
  mean /= samples.size();
  double energy = 0;
  for (float sample : samples) energy += (sample - mean) * (sample - mean);
  if (std::sqrt(energy / samples.size()) < 0.003) return 0;

  const int min_lag = static_cast<int>(sample_rate / kMaxFrequency);
  const int max_lag = static_cast<int>(sample_rate / kMinFrequency);
  const size_t frame = samples.size() - max_lag;
  std::vector<double> normalized(max_lag + 1, 1.0);
  double cumulative = 0;
  for (int lag = 1; lag <= max_lag; ++lag) {
    double difference = 0;
    for (size_t i = 0; i < frame; ++i) {
      double delta = samples[i] - samples[i + lag];
      difference += delta * delta;
    }
    cumulative += difference;
    normalized[lag] = cumulative > 0 ? difference * lag / cumulative : 1.0;
  }
  int lag = min_lag;
  while (lag < max_lag && normalized[lag] >= kThreshold) ++lag;
  if (lag >= max_lag) return 0;
  while (lag + 1 <= max_lag && normalized[lag + 1] < normalized[lag]) ++lag;
  double refined = lag;
  if (lag > 1 && lag < max_lag) {
    const double a = normalized[lag - 1], b = normalized[lag], c = normalized[lag + 1];
    const double denominator = a - 2 * b + c;
    if (std::abs(denominator) > 1e-12) refined += 0.5 * (a - c) / denominator;
  }
  const double frequency = sample_rate / refined;
  return frequency >= kMinFrequency && frequency <= kMaxFrequency ? frequency : 0;
}
