// Christmas tree display: a star (the ceiling light) and big ornaments (one light each) that are
// dull when their light is off and shine when it is on. Tapping one toggles its light; ornaments
// sway on their branch and the star bobs, with a burst of sparkles. Lit things sparkle, the bulbs on the light strings
// twinkle and snow falls in front of it all.
//
// The images and positions come from tree/make_images.py (tree/tree_layout.h is generated).
// A tap changes the picture at once; if Home Assistant hasn't confirmed the new state within
// PENDING_MS it goes back to what Home Assistant says (e.g. a light that doesn't exist yet).
//
// Redraw budget: LVGL keeps 32 dirty areas per frame and redraws the whole screen past that,
// so snow moves half its flakes per frame, one area per flake (as in lab/lab_tubes.h).
// Images are only ever moved, never rotated or zoomed: transformed images with alpha are slow
// in LVGL 8 and three at once lagged and rebooted the display.
#pragma once

#include <algorithm>
#include <cmath>
#include <functional>

#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "lvgl.h"
#include "tree_layout.h"

namespace tree {

static const char *const TAG = "tree";

constexpr int STAR = 0;                // item 0 is the star, 1.. the ornaments
constexpr int ITEMS = 1 + ORNAMENTS;
constexpr int FLAKES = 20;
constexpr int SPARKLES = 10;
constexpr int SPARKLE_SIZE = 24;
constexpr uint32_t PENDING_MS = 4000;  // keep a tapped state this long without confirmation
constexpr float FRAME_S = 0.04f;       // tick() runs every 40 ms

struct Item {
  lv_obj_t *img = nullptr;
  const lv_img_dsc_t *on_src = nullptr;
  const lv_img_dsc_t *off_src = nullptr;
  bool ha_on = false;  // last state from Home Assistant (off until it says anything)
  bool shown = false;
  bool pending = false;
  uint32_t pending_until = 0;
  int anim = -1;  // frames since tapped, -1 when still
  int cx = 0, cy = 0, r = 0;  // where sparkles go
  int x = 0, y = 0;           // resting position of the image
};

struct Sparkle {
  lv_obj_t *obj = nullptr;
  int age = -1;
  int life = 14;
};

struct Flake {
  lv_obj_t *obj = nullptr;
  float x = 0, y = 0, speed = 1, phase = 0;
  int land = 460;
  int size = 3;
  int drawn_x = 0, drawn_y = 0;
};

inline Item items[ITEMS];
inline Sparkle sparkles[SPARKLES];
inline Flake flakes[FLAKES];
inline lv_obj_t *bulbs[BULBS];
inline lv_obj_t *page_obj = nullptr;
inline std::function<void(int, bool)> send;
inline uint32_t frames = 0;
inline uint32_t frames_logged_at = 0;

inline uint32_t rng = 0x2545F491;
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

inline void show(int i, bool on) {
  Item &it = items[i];
  if (it.shown == on && lv_img_get_src(it.img) != nullptr)
    return;
  it.shown = on;
  lv_img_set_src(it.img, on ? it.on_src : it.off_src);
}

inline void spawn_sparkle(const Item &it);

// Toggle item i as if tapped
inline void tap(int i) {
  if (i < 0 || i >= ITEMS || items[i].img == nullptr)
    return;
  Item &it = items[i];
  const bool on = !it.shown;
  show(i, on);
  it.pending = true;
  it.pending_until = esphome::millis() + PENDING_MS;
  it.anim = 0;
  if (on)
    for (int k = 0; k < 4; k++)
      spawn_sparkle(it);
  ESP_LOGD(TAG, "Tapped %d: %s", i, on ? "on" : "off");
  if (send)
    send(i, on);
}

inline void click_cb(lv_event_t *e) { tap((int) (intptr_t) lv_event_get_user_data(e)); }

// State from Home Assistant
inline void set_state(int i, bool on) {
  if (i < 0 || i >= ITEMS)
    return;
  Item &it = items[i];
  it.ha_on = on;
  if (it.img == nullptr)  // page not built yet; setup's caller passes the state on
    return;
  if (!it.pending || on == it.shown) {
    it.pending = false;
    show(i, on);
  }
}

inline void spawn_flake(Flake &f, bool at_top) {
  f.size = 2 + rnd() % 4;
  f.x = frand(0, 480 - f.size);
  f.y = at_top ? -f.size - frand(0, 60) : frand(0, 430);
  f.speed = frand(0.5f, 1.0f) + f.size * 0.15f;
  f.phase = frand(0, 6.28f);
  f.land = SNOW_Y + rnd() % 36;
  lv_obj_set_size(f.obj, f.size, f.size);
  lv_obj_set_style_bg_opa(f.obj, (lv_opa_t) (140 + f.size * 25), 0);
}

inline lv_obj_t *make_img(lv_obj_t *page, const lv_img_dsc_t *src, int x, int y) {
  lv_obj_t *img = lv_img_create(page);
  lv_obj_clear_flag(img, LV_OBJ_FLAG_SCROLLABLE);
  lv_img_set_src(img, src);
  lv_obj_set_pos(img, x, y);
  return img;
}

// on_src / off_src: star first, then the ornaments
inline void setup(lv_obj_t *page, const lv_img_dsc_t *const on_src[ITEMS], const lv_img_dsc_t *const off_src[ITEMS],
                  const lv_img_dsc_t *sparkle_src, std::function<void(int, bool)> changed) {
  send = std::move(changed);
  page_obj = page;
  rng ^= esphome::millis() * 2654435761u;

  // Bulbs first, so they sit behind the ornaments
  for (int b = 0; b < BULBS; b++) {
    lv_obj_t *bulb = lv_obj_create(page);
    plain(bulb);
    lv_obj_set_size(bulb, 8, 11);
    lv_obj_set_pos(bulb, BULB_POS[b][0] - 4, BULB_POS[b][1] - 5);
    lv_obj_set_style_radius(bulb, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(bulb, lv_color_hex(BULB_COLOR[b]), 0);
    lv_obj_set_style_bg_opa(bulb, LV_OPA_COVER, 0);
    lv_obj_set_style_shadow_color(bulb, lv_color_hex(BULB_COLOR[b]), 0);
    lv_obj_set_style_shadow_width(bulb, 10, 0);
    lv_obj_set_style_shadow_opa(bulb, LV_OPA_70, 0);
    bulbs[b] = bulb;
  }

  for (int i = 0; i < ITEMS; i++) {
    Item &it = items[i];
    it.on_src = on_src[i];
    it.off_src = off_src[i];
    if (i == STAR) {
      it.x = STAR_X;
      it.y = STAR_Y;
      it.cx = STAR_X + STAR_SIZE / 2;
      it.cy = STAR_Y + STAR_SIZE / 2;
      it.r = STAR_R + 8;
    } else {
      const int k = i - 1;
      it.x = ORN_X[k];
      it.y = ORN_Y[k];
      it.cx = ORN_X[k] + ORN_CX;
      it.cy = ORN_Y[k] + ORN_CY;
      it.r = ORN_R;
    }
    it.img = make_img(page, off_src[i], it.x, it.y);
    it.shown = false;
    lv_obj_add_flag(it.img, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(it.img, click_cb, LV_EVENT_CLICKED, (void *) (intptr_t) i);
  }

  for (Sparkle &s : sparkles) {
    s.obj = make_img(page, sparkle_src, 0, 0);
    lv_obj_clear_flag(s.obj, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(s.obj, LV_OBJ_FLAG_HIDDEN);
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

// Ornaments sway sideways on their branch, the star bobs up. Only moves the image.
inline void tick_item(int i, uint32_t now) {
  Item &it = items[i];
  if (it.pending && (int32_t) (now - it.pending_until) >= 0) {
    it.pending = false;
    if (it.shown != it.ha_on)
      ESP_LOGW(TAG, "No confirmation for %d from Home Assistant, showing its state again", i);
    show(i, it.ha_on);
  }
  if (it.anim < 0)
    return;
  const float t = it.anim++ * FRAME_S;
  int dx = 0, dy = 0;
  if (t > 2.0f) {
    it.anim = -1;
  } else if (i == STAR) {
    dy = -(int) lroundf(9.0f * expf(-t / 0.35f) * fabsf(sinf(3.1416f * t / 0.3f)));
  } else {
    const float s = 7.0f * expf(-t / 0.55f) * sinf(6.2832f * t / 0.8f);
    dx = (int) lroundf(s);
    dy = -(int) lroundf(fabsf(s) * 0.2f);  // a little up at each end of the swing
  }
  if (lv_obj_get_x(it.img) != it.x + dx || lv_obj_get_y(it.img) != it.y + dy)
    lv_obj_set_pos(it.img, it.x + dx, it.y + dy);
}

inline void spawn_sparkle(const Item &it) {
  for (Sparkle &s : sparkles) {
    if (s.age >= 0)
      continue;
    const float a = frand(0, 6.2832f);
    const float d = it.r * frand(0.35f, 1.1f);
    lv_obj_set_pos(s.obj, it.cx + (int) (cosf(a) * d) - SPARKLE_SIZE / 2, it.cy + (int) (sinf(a) * d) - SPARKLE_SIZE / 2);
    lv_obj_set_style_img_opa(s.obj, LV_OPA_TRANSP, 0);
    lv_obj_clear_flag(s.obj, LV_OBJ_FLAG_HIDDEN);
    s.life = 10 + rnd() % 10;
    s.age = 0;
    return;
  }
}

inline void tick_sparkles() {
  for (Sparkle &s : sparkles) {
    if (s.age < 0)
      continue;
    if (++s.age >= s.life) {
      s.age = -1;
      lv_obj_add_flag(s.obj, LV_OBJ_FLAG_HIDDEN);
      continue;
    }
    lv_obj_set_style_img_opa(s.obj, (lv_opa_t) (255 * sinf(3.14159f * s.age / s.life)), 0);
  }
  if (frames % 3 != 0)
    return;

  // A new sparkle on something lit; the star gets twice the share
  int lit[ITEMS + 1], n = 0;
  for (int i = 0; i < ITEMS; i++) {
    if (!items[i].shown)
      continue;
    lit[n++] = i;
    if (i == STAR)
      lit[n++] = i;
  }
  if (n == 0)
    return;
  spawn_sparkle(items[lit[rnd() % n]]);
}

// Half the flakes per frame, with a double step: each dirty area costs a redraw and a flush
inline void tick_snow() {
  for (int n = frames % 2; n < FLAKES; n += 2) {
    Flake &f = flakes[n];
    f.y += 2 * f.speed;
    f.phase += 0.1f;
    f.x += sinf(f.phase) * 0.7f;
    if (f.y > f.land) {  // landed in the snow
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
    const lv_area_t dirty = {(lv_coord_t) std::min(x, f.drawn_x), (lv_coord_t) std::min(y, f.drawn_y),
                             (lv_coord_t) (std::max(x, f.drawn_x) + f.size - 1),
                             (lv_coord_t) (std::max(y, f.drawn_y) + f.size - 1)};
    lv_obj_invalidate_area(page_obj, &dirty);
    lv_obj_set_pos(f.obj, x, y);
    f.drawn_x = x;
    f.drawn_y = y;
  }
}

// Called every 40 ms while the screen is lit
inline void tick() {
  const uint32_t now = esphome::millis();
  for (int i = 0; i < ITEMS; i++)
    tick_item(i, now);
  tick_sparkles();
  tick_snow();

  if (frames % 3 == 0) {  // twinkle one bulb
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

}  // namespace tree
