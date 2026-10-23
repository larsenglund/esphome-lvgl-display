#include "screenshot.h"

#include <algorithm>
#include <memory>
#include <new>

#include <esp_http_server.h>
#include <esp_lcd_panel_rgb.h>

#include "esphome/core/log.h"

namespace esphome {
namespace display_screenshot {

static const char *const TAG = "display_screenshot";
static const char *const PATH = "/screenshot";

// ST7701S keeps its esp_lcd panel handle protected; read it through a derived-class member pointer.
struct PanelAccess : st7701s::ST7701S {
  static esp_lcd_panel_handle_t get(st7701s::ST7701S *display) { return display->*(&PanelAccess::handle_); }
};

void Screenshot::setup() {
  this->base_->init();
  this->base_->add_handler(this);
}

void Screenshot::dump_config() { ESP_LOGCONFIG(TAG, "Display screenshot at http://<device>%s", PATH); }

bool Screenshot::canHandle(AsyncWebServerRequest *request) const {
  return request->method() == HTTP_GET && request->url() == PATH;
}

void Screenshot::handleRequest(AsyncWebServerRequest *request) {
  void *frame_buffer = nullptr;
  esp_lcd_panel_handle_t panel = PanelAccess::get(this->display_);
  if (panel == nullptr || esp_lcd_rgb_panel_get_frame_buffer(panel, 1, &frame_buffer) != ESP_OK ||
      frame_buffer == nullptr) {
    request->send(503, "text/plain", "No frame buffer");
    return;
  }

  // RGB565 BMP with bit field masks, rows stored top to bottom (negative height)
  const uint32_t width = this->display_->get_native_width();
  const uint32_t height = this->display_->get_native_height();
  const uint32_t row_bytes = width * 2;
  const uint32_t image_bytes = row_bytes * height;
  uint8_t header[66] = {};
  auto put16 = [&header](size_t at, uint16_t value) {
    header[at] = value & 0xFF;
    header[at + 1] = value >> 8;
  };
  auto put32 = [&header](size_t at, uint32_t value) {
    for (size_t i = 0; i < 4; i++)
      header[at + i] = (value >> (8 * i)) & 0xFF;
  };
  header[0] = 'B';
  header[1] = 'M';
  put32(2, sizeof(header) + image_bytes);
  put32(10, sizeof(header));
  put32(14, 40);
  put32(18, width);
  put32(22, static_cast<uint32_t>(-static_cast<int32_t>(height)));
  put16(26, 1);
  put16(28, 16);
  put32(30, 3);  // BI_BITFIELDS
  put32(34, image_bytes);
  put32(54, 0xF800);
  put32(58, 0x07E0);
  put32(62, 0x001F);

  // The frame buffer holds each pixel high byte first, BMP wants low byte first, so swap while
  // streaming a few rows at a time. The panel may be mid-update, which can at worst tear the image.
  const size_t chunk = row_bytes * 8;
  std::unique_ptr<uint8_t[]> buffer(new (std::nothrow) uint8_t[chunk]);
  if (!buffer) {
    request->send(503, "text/plain", "Out of memory");
    return;
  }
  httpd_req_t *req = *request;
  httpd_resp_set_type(req, "image/bmp");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  if (httpd_resp_send_chunk(req, reinterpret_cast<const char *>(header), sizeof(header)) != ESP_OK)
    return;
  const auto *pixels = static_cast<const uint8_t *>(frame_buffer);
  for (size_t sent = 0; sent < image_bytes; sent += chunk) {
    const size_t length = std::min<size_t>(chunk, image_bytes - sent);
    for (size_t i = 0; i < length; i += 2) {
      buffer[i] = pixels[sent + i + 1];
      buffer[i + 1] = pixels[sent + i];
    }
    if (httpd_resp_send_chunk(req, reinterpret_cast<const char *>(buffer.get()), length) != ESP_OK) {
      ESP_LOGW(TAG, "Client went away during screenshot");
      return;
    }
  }
  httpd_resp_send_chunk(req, nullptr, 0);
}

}  // namespace display_screenshot
}  // namespace esphome
