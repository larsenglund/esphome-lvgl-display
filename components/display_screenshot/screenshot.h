#pragma once

#include "esphome/core/component.h"
#include "esphome/components/st7701s/st7701s.h"
#include "esphome/components/web_server_base/web_server_base.h"

namespace esphome {
namespace display_screenshot {

/// Serves the panel's frame buffer (what is on the glass, including LVGL's top layer) as a 16-bit BMP.
class Screenshot : public AsyncWebHandler, public Component {
 public:
  explicit Screenshot(web_server_base::WebServerBase *base) : base_(base) {}
  void set_display(st7701s::ST7701S *display) { this->display_ = display; }

  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::WIFI - 1.0f; }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;

 protected:
  web_server_base::WebServerBase *base_;
  st7701s::ST7701S *display_{nullptr};
};

}  // namespace display_screenshot
}  // namespace esphome
