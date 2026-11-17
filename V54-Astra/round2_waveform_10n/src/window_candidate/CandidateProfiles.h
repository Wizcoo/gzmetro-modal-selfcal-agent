#pragma once
#include "ModalSelfCal.h"

// Offline-review profiles, exactly matching the ten-night native replay.
// None has passed the combined full-night range and physical-waveform target.
namespace astra_review {
inline ModalSelfCalConfig FadeExit07() {
    ModalSelfCalConfig c;
    c.max_frame_dev = 0.0;
    c.fade_x_enhancements_with_gate = true;
    return c; // current_fade07: original 07:00 exit, W3/S1/S2 retained.
}
inline ModalSelfCalConfig FadeExit08() {
    auto c = FadeExit07();
    c.x_apply_end_h = 32.0;
    return c; // current_fade08: moves exit to 08:00, does not remove it.
}
inline ModalSelfCalConfig ReducedLag() {
    ModalSelfCalConfig c;
    c.max_frame_dev = 0.0;
    c.enable_x_w3_filter = false;
    return c; // no_w3: about one minute less lag; worse full-night range.
}
} // namespace astra_review
