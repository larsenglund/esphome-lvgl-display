// Christmas lab display: four glass tubes (R, G, B, W) of bubbling liquid that set an RGBW light.
//
// The glass and liquid widgets come from lab/tube.yaml; this adds the wavy surface, bubbles,
// graduation marks, twinkling bulbs and falling snow, follows the finger while a tube is dragged,
// and keeps the tubes in step with the light's state in Home Assistant.
// Positions must match lab/make_background.py.
//
// The light only has colour and white modes (no RGB and white at once), so raising the white
// tube drains the colour tubes and the other way round.
//
// Redraw budget: LVGL keeps 32 dirty areas per frame and redraws the whole screen past that.
// So each frame first marks one area per tube (its liquid) and one per snowflake (old and new
// position together); the bubbles and waves inside those areas then add no areas of their own.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <functional>
#include <string>

#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "lvgl.h"

namespace lab {

static const char *const TAG = "lab";

constexpr int TUBES = 4;
constexpr int WHITE = 3;
constexpr int INNER_W = 58;   // tube.yaml: width 64 minus 2 x 3 px border
constexpr int INNER_H = 286;  // tube.yaml: height 292 minus 2 x 3 px border
constexpr int WAVE_A = 5;     // the surface moves up to this many px up and down
constexpr int BUBBLES = 9;
constexpr int BULBS = 7;
constexpr int FLAKES = 20;
constexpr uint32_t HOLDOFF_MS = 5000;  // ignore Home Assistant this long after sending a change

constexpr int BULB_X[BULBS] = {130, 165, 200, 240, 280, 315, 350};
constexpr uint32_t BULB_COLOR[BULBS] = {0xFF2D2D, 0xFFC531, 0x3DDC4A, 0x3D8BFF, 0xFF2D2D, 0xFFC531, 0x3DDC4A};
constexpr uint32_t BUBBLE_COLOR[TUBES] = {0xFFD9D2, 0xF2FFD8, 0xDDF2FF, 0x8AA3B6};
constexpr uint32_t LIQUID_TOP[TUBES] = {0xFF6B5E, 0xB6FF4A, 0x6EC6FF, 0xFFFFFF};  // as in lab.yaml
constexpr uint32_t ACCENT[TUBES] = {0xFF3B30, 0x8BE02E, 0x3A9BFF, 0xFFFFFF};
constexpr uint32_t GLASS_EDGE = 0xBFD8E8;
constexpr lv_opa_t LIQUID_OPA = 235;  // tube.yaml bg_opa 92%

struct Bubble {
  lv_obj_t *obj = nullptr;
  float depth = 0;  // px of the bubble's bottom above the bottom of the liquid
  float speed = 1;  // px per frame
  float x = 0;
  float phase = 0;
  int size = 4;
  bool visible = false;
};

struct Tube {
  lv_obj_t *glass = nullptr;
  lv_obj_t *liquid = nullptr;  // body below the waves
  lv_obj_t *wave = nullptr;    // strip with the wavy surface, drawn in wave_draw_cb
  Bubble bubbles[BUBBLES];
  float shown = 0;   // level on screen, 0-100, eases toward target
  float target = 0;  // level set by the finger or Home Assistant
  int drawn_h = -1;  // px of liquid up to the middle of the waves
  float wave_phase = 0;
  float slosh = 0;  // extra wave height after the level moved
};

struct Flake {
  lv_obj_t *obj = nullptr;
  float x = 0, y = 0, speed = 1, phase = 0;
  int land = 460;  // where it disappears into the snowdrift
  int size = 3;
  int drawn_x = 0, drawn_y = 0;
};

struct LightState {
  bool on = false;
  bool white = false;
  int rgb[3] = {0, 0, 0};  // full brightness colour, as in the rgb_color attribute
  float brightness = 0;    // 0-255
};

inline Tube tubes[TUBES];
inline lv_obj_t *bulbs[BULBS];
inline Flake flakes[FLAKES];
inline lv_obj_t *page_obj = nullptr;
inline int touching = -1;
inline uint32_t holdoff_until = 0;
inline std::function<void()> on_change;
inline LightState ha;
inline bool ha_dirty = false;
inline uint32_t frames = 0;
inline uint32_t frames_logged_at = 0;

inline uint32_t rng = 0x9E3779B9;
inline uint32_t rnd() {
  rng ^= rng << 13;
  rng ^= rng >> 17;
  rng ^= rng << 5;
  return rng;
}
inline float frand(float lo, float hi) { return lo + (hi - lo) * (rnd() & 0xFFFF) / 65535.0f; }

inline void plain(lv_obj_t *obj) {
  lv_obj_remove_style_all(obj);
  lv_obj_clear_flag(obj, LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE);
}

// A new bubble just below the bottom of the liquid, or anywhere in it
inline void spawn(Bubble &b, int body_h, bool anywhere) {
  b.size = 3 + rnd() % 8;
  b.x = frand(3, INNER_W - b.size - 3);
  b.depth = anywhere ? frand(0, std::max(1, body_h - b.size)) : -frand(b.size, 40);
  b.speed = frand(0.6f, 1.4f) + b.size * 0.08f;
  b.phase = frand(0, 6.28f);
  lv_obj_set_size(b.obj, b.size, b.size);
}

inline void spawn_flake(Flake &f, bool at_top) {
  f.size = 2 + rnd() % 4;
  f.x = frand(0, 480 - f.size);
  f.y = at_top ? -f.size - frand(0, 60) : frand(0, 430);
  f.speed = frand(0.5f, 1.0f) + f.size * 0.15f;
  f.phase = frand(0, 6.28f);
  f.land = 438 + rnd() % 36;
  lv_obj_set_size(f.obj, f.size, f.size);
  lv_obj_set_style_bg_opa(f.obj, (lv_opa_t) (140 + f.size * 25), 0);
}

// Surface height in the wave strip at column x: 0 (top) to 2 * WAVE_A
inline int wave_y(const Tube &t, int x) {
  const float amp = std::min((float) WAVE_A, 1.5f + t.slosh);
  const float s = 0.7f * sinf(x * 0.16f + t.wave_phase) + 0.3f * sinf(x * 0.37f - t.wave_phase * 1.7f);
  return std::max(0, std::min(2 * WAVE_A, (int) lroundf(WAVE_A + amp * s)));
}

inline void wave_draw_cb(lv_event_t *e) {
  const int i = (int) (intptr_t) lv_event_get_user_data(e);
  const Tube &t = tubes[i];
  lv_draw_ctx_t *ctx = lv_event_get_draw_ctx(e);
  lv_area_t c;
  lv_obj_get_coords(t.wave, &c);

  lv_draw_rect_dsc_t liquid;
  lv_draw_rect_dsc_init(&liquid);
  liquid.bg_color = lv_color_hex(LIQUID_TOP[i]);
  liquid.bg_opa = LIQUID_OPA;
  lv_draw_rect_dsc_t crest;
  lv_draw_rect_dsc_init(&crest);
  crest.bg_color = lv_color_white();
  crest.bg_opa = LV_OPA_50;

  for (int x = 0; x < INNER_W; x += 2) {
    const int y = c.y1 + wave_y(t, x);
    const lv_area_t col = {(lv_coord_t) (c.x1 + x), (lv_coord_t) y, (lv_coord_t) (c.x1 + x + 1), c.y2};
    lv_draw_rect(ctx, &liquid, &col);
    const lv_area_t top = {col.x1, col.y1, col.x2, (lv_coord_t) (y + 1)};
    lv_draw_rect(ctx, &crest, &top);
  }
}

// Exclusive modes: white or colour
inline void keep_one_mode(int i) {
  if (tubes[i].target <= 0)
    return;
  if (i == WHITE) {
    for (int k = 0; k < WHITE; k++)
      tubes[k].target = 0;
  } else {
    tubes[WHITE].target = 0;
  }
}

inline float level_at(lv_obj_t *glass, const lv_point_t &p) {
  lv_area_t a;
  lv_obj_get_content_coords(glass, &a);
  float level = (a.y2 - p.y) * 100.0f / (a.y2 - a.y1);
  if (level < 4)  // easy to drain completely
    level = 0;
  if (level > 97)
    level = 100;
  return std::max(0.0f, std::min(100.0f, level));
}

inline void touch_cb(lv_event_t *e) {
  const int i = (int) (intptr_t) lv_event_get_user_data(e);
  const lv_event_code_t code = lv_event_get_code(e);
  if (code == LV_EVENT_PRESSED || code == LV_EVENT_PRESSING) {
    lv_indev_t *indev = lv_indev_get_act();
    if (indev == nullptr)
      return;
    lv_point_t p;
    lv_indev_get_point(indev, &p);
    touching = i;
    tubes[i].target = level_at(tubes[i].glass, p);
    keep_one_mode(i);
  } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
    if (touching != i)
      return;
    touching = -1;
    holdoff_until = esphome::millis() + HOLDOFF_MS;
    ESP_LOGD(TAG, "Tubes R %.0f G %.0f B %.0f W %.0f", tubes[0].target, tubes[1].target, tubes[2].target,
             tubes[3].target);
    if (on_change)
      on_change();
  }
}

// Set all tubes at once (0-100) and send them, as if they had been dragged.
// White wins over colour, like on the light.
inline void set_levels(float red, float green, float blue, float white) {
  const float levels[TUBES] = {red, green, blue, white};
  for (int k = 0; k < TUBES; k++)
    tubes[k].target = std::max(0.0f, std::min(100.0f, levels[k]));
  keep_one_mode(WHITE);
  holdoff_until = esphome::millis() + HOLDOFF_MS;
  if (on_change)
    on_change();
}

// What to send: 0 = off, 1 = white, 2 = colour
inline int send_mode() {
  if (tubes[WHITE].target > 0)
    return 1;
  for (int k = 0; k < WHITE; k++)
    if (tubes[k].target > 0)
      return 2;
  return 0;
}
inline int level255(int i) { return (int) lroundf(tubes[i].target * 2.55f); }
inline int send_brightness() { return std::max({level255(0), level255(1), level255(2), 1}); }
// Colour at full brightness; send_brightness() carries the level
inline int send_rgb(int k) { return (int) lroundf(level255(k) * 255.0f / send_brightness()); }

// Latest state from Home Assistant, applied by tick() once no one is dragging
inline void ha_update(bool on, const std::string &color_mode, const std::string &rgb, float brightness) {
  ha.on = on;
  ha.white = color_mode == "white";
  const size_t start = rgb.find_first_of("0123456789");
  int r, g, b;
  if (start != std::string::npos && sscanf(rgb.c_str() + start, "%d, %d, %d", &r, &g, &b) == 3) {
    ha.rgb[0] = r;
    ha.rgb[1] = g;
    ha.rgb[2] = b;
  }
  if (!std::isnan(brightness))
    ha.brightness = brightness;
  ha_dirty = true;
}

inline void apply_ha() {
  for (int k = 0; k < TUBES; k++)
    tubes[k].target = 0;
  if (!ha.on)
    return;
  const float level = ha.brightness / 2.55f;
  if (ha.white) {
    tubes[WHITE].target = level;
  } else {
    for (int k = 0; k < WHITE; k++)
      tubes[k].target = ha.rgb[k] / 255.0f * level;
  }
}

inline void setup(lv_obj_t *page, lv_obj_t *const glass[TUBES], lv_obj_t *const liquid[TUBES],
                  std::function<void()> changed) {
  on_change = std::move(changed);
  page_obj = page;
  rng ^= esphome::millis() * 2654435761u;

  for (int i = 0; i < TUBES; i++) {
    Tube &t = tubes[i];
    t.glass = glass[i];
    t.liquid = liquid[i];
    lv_obj_add_event_cb(t.glass, touch_cb, LV_EVENT_ALL, (void *) (intptr_t) i);
    lv_obj_add_flag(t.liquid, LV_OBJ_FLAG_HIDDEN);

    // Wavy surface, right above the liquid (under the shine and the paper label)
    t.wave = lv_obj_create(t.glass);
    plain(t.wave);
    lv_obj_set_size(t.wave, INNER_W, 2 * WAVE_A);
    lv_obj_add_flag(t.wave, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_event_cb(t.wave, wave_draw_cb, LV_EVENT_DRAW_MAIN, (void *) (intptr_t) i);
    lv_obj_move_to_index(t.wave, lv_obj_get_index(t.liquid) + 1);
    t.wave_phase = frand(0, 6.28f);

    for (Bubble &b : t.bubbles) {
      b.obj = lv_obj_create(t.liquid);
      plain(b.obj);
      lv_obj_set_style_radius(b.obj, LV_RADIUS_CIRCLE, 0);
      lv_obj_set_style_bg_color(b.obj, lv_color_hex(BUBBLE_COLOR[i]), 0);
      lv_obj_set_style_bg_opa(b.obj, LV_OPA_40, 0);
      lv_obj_set_style_border_color(b.obj, lv_color_hex(BUBBLE_COLOR[i]), 0);
      lv_obj_set_style_border_opa(b.obj, LV_OPA_90, 0);
      lv_obj_set_style_border_width(b.obj, 1, 0);
      lv_obj_add_flag(b.obj, LV_OBJ_FLAG_HIDDEN);
      spawn(b, INNER_H, true);
    }

    // Graduation marks, every 10 % (not under the paper label at the top)
    for (int j = 1; j <= 8; j++) {
      lv_obj_t *tick = lv_obj_create(t.glass);
      plain(tick);
      const int w = j % 5 == 0 ? 14 : 8;
      lv_obj_set_size(tick, w, 2);
      lv_obj_set_pos(tick, INNER_W - w - 4, INNER_H - j * INNER_H / 10);
      lv_obj_set_style_bg_color(tick, lv_color_white(), 0);
      lv_obj_set_style_bg_opa(tick, LV_OPA_60, 0);
    }
  }

  // Bulbs on the wire drawn in the background
  for (int i = 0; i < BULBS; i++) {
    lv_obj_t *bulb = lv_obj_create(page);
    plain(bulb);
    const float wire = 6 + 20 * sinf(3.14159f * BULB_X[i] / 480);
    lv_obj_set_size(bulb, 10, 14);
    lv_obj_set_pos(bulb, BULB_X[i] - 5, (int) wire + 7);
    lv_obj_set_style_radius(bulb, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(bulb, lv_color_hex(BULB_COLOR[i]), 0);
    lv_obj_set_style_bg_opa(bulb, LV_OPA_COVER, 0);
    lv_obj_set_style_shadow_color(bulb, lv_color_hex(BULB_COLOR[i]), 0);
    lv_obj_set_style_shadow_width(bulb, 12, 0);
    lv_obj_set_style_shadow_opa(bulb, LV_OPA_70, 0);
    bulbs[i] = bulb;
  }

  // Snow, in front of everything (flakes aren't clickable, so touches go through)
  for (Flake &f : flakes) {
    f.obj = lv_obj_create(page);
    plain(f.obj);
    lv_obj_set_style_radius(f.obj, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(f.obj, lv_color_hex(0xF4FAFF), 0);
    spawn_flake(f, false);
    f.drawn_x = (int) f.x;
    f.drawn_y = (int) f.y;
    lv_obj_set_pos(f.obj, f.drawn_x, f.drawn_y);
  }
}

// Body and wave strip for a liquid level of h px
inline void draw_level(int i, int h) {
  Tube &t = tubes[i];
  if (h == t.drawn_h)
    return;
  t.drawn_h = h;
  if (h <= 0) {
    lv_obj_add_flag(t.liquid, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(t.wave, LV_OBJ_FLAG_HIDDEN);
  } else {
    lv_obj_clear_flag(t.wave, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_pos(t.wave, 0, INNER_H - h - WAVE_A);
    const int body = h - WAVE_A;
    if (body > 0) {
      lv_obj_clear_flag(t.liquid, LV_OBJ_FLAG_HIDDEN);
      lv_obj_set_pos(t.liquid, 0, INNER_H - body);
      lv_obj_set_size(t.liquid, INNER_W, body);
    } else {
      lv_obj_add_flag(t.liquid, LV_OBJ_FLAG_HIDDEN);
    }
  }
  // The glass picks up the liquid's colour as it fills
  const lv_opa_t mix = (lv_opa_t) (t.shown * 2.0f);  // up to 200 of 255
  lv_obj_set_style_border_color(t.glass, lv_color_mix(lv_color_hex(ACCENT[i]), lv_color_hex(GLASS_EDGE), mix), 0);
}

inline void tick_tube(int i) {
  Tube &t = tubes[i];
  const int prev_h = std::max(0, t.drawn_h);
  const float rate = touching == i ? 0.6f : 0.12f;
  t.shown += (t.target - t.shown) * rate;
  if (fabsf(t.target - t.shown) < 0.1f)
    t.shown = t.target;
  const int h = (int) lroundf(t.shown * INNER_H / 100);
  if (h <= 0 && prev_h <= 0)
    return;

  // One dirty area for everything that moves in this tube
  lv_area_t a;
  lv_obj_get_content_coords(t.glass, &a);
  lv_area_t dirty = a;
  dirty.y1 = std::max(a.y1, (lv_coord_t) (a.y2 - std::max(h, prev_h) - WAVE_A - 1));
  lv_obj_invalidate_area(t.glass, &dirty);

  t.slosh = std::min((float) WAVE_A, t.slosh * 0.95f + abs(h - prev_h) * 0.12f);
  t.wave_phase += 0.22f;
  draw_level(i, h);
  if (h > 0)
    lv_obj_invalidate(t.wave);

  const int body = h - WAVE_A;
  const int active = body <= 0 ? 0 : 2 + (int) (t.shown / 100 * (BUBBLES - 2));
  for (int k = 0; k < BUBBLES; k++) {
    Bubble &b = t.bubbles[k];
    if (k >= active) {
      if (b.visible) {
        lv_obj_add_flag(b.obj, LV_OBJ_FLAG_HIDDEN);
        b.visible = false;
        spawn(b, body, false);
      }
      continue;
    }
    b.depth += b.speed;
    b.phase += 0.18f;
    if (b.depth > body)  // popped at the surface
      spawn(b, body, false);
    const int x = (int) lroundf(b.x + sinf(b.phase) * 1.6f);
    const int y = body - (int) b.depth - b.size;
    lv_obj_set_pos(b.obj, x, y);
    if (!b.visible) {
      lv_obj_clear_flag(b.obj, LV_OBJ_FLAG_HIDDEN);
      b.visible = true;
    }
  }
}

// Half the flakes per frame, with a double step: each dirty area costs a redraw and a flush
inline void tick_snow() {
  for (int n = frames % 2; n < FLAKES; n += 2) {
    Flake &f = flakes[n];
    f.y += 2 * f.speed;
    f.phase += 0.1f;
    f.x += sinf(f.phase) * 0.7f;
    if (f.y > f.land) {  // landed in the snowdrift
      lv_obj_invalidate(f.obj);
      spawn_flake(f, true);
      f.drawn_x = (int) f.x;
      f.drawn_y = (int) f.y;
      lv_obj_set_pos(f.obj, f.drawn_x, f.drawn_y);
      continue;
    }
    const int x = (int) lroundf(f.x), y = (int) lroundf(f.y);
    if (x == f.drawn_x && y == f.drawn_y)
      continue;
    // Old and new position as one dirty area
    const lv_area_t dirty = {(lv_coord_t) std::min(x, f.drawn_x), (lv_coord_t) std::min(y, f.drawn_y),
                             (lv_coord_t) (std::max(x, f.drawn_x) + f.size - 1),
                             (lv_coord_t) (std::max(y, f.drawn_y) + f.size - 1)};
    lv_obj_invalidate_area(page_obj, &dirty);
    lv_obj_set_pos(f.obj, x, y);
    f.drawn_x = x;
    f.drawn_y = y;
  }
}

// Called about 25 times a second
inline void tick() {
  const uint32_t now = esphome::millis();
  if (ha_dirty && touching < 0 && (int32_t) (now - holdoff_until) >= 0) {
    apply_ha();
    ha_dirty = false;
  }

  for (int i = 0; i < TUBES; i++)
    tick_tube(i);
  tick_snow();

  // Twinkle one bulb every few frames
  if (frames % 4 == 0) {
    lv_obj_t *bulb = bulbs[rnd() % BULBS];
    const bool dim = rnd() % 3 == 0;
    lv_obj_set_style_bg_opa(bulb, dim ? LV_OPA_40 : LV_OPA_COVER, 0);
    lv_obj_set_style_shadow_opa(bulb, dim ? LV_OPA_10 : LV_OPA_70, 0);
  }

  frames++;
  if (now - frames_logged_at >= 10000) {
    ESP_LOGD(TAG, "%.1f frames/s", frames * 1000.0f / (now - frames_logged_at));
    frames = 0;
    frames_logged_at = now;
  }
}

}  // namespace lab
