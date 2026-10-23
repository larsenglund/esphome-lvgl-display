"""Serve what is on an ST7701S panel as a BMP image at http://<device>/screenshot."""

import esphome.codegen as cg
from esphome.components import socket, web_server_base
from esphome.components.st7701s.display import ST7701S
from esphome.components.web_server_base import CONF_WEB_SERVER_BASE_ID
import esphome.config_validation as cv
from esphome.const import CONF_DISPLAY_ID, CONF_ID

DEPENDENCIES = ["network", "display"]
AUTO_LOAD = ["web_server_base", "socket"]

display_screenshot_ns = cg.esphome_ns.namespace("display_screenshot")
Screenshot = display_screenshot_ns.class_("Screenshot", cg.Component)

CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(Screenshot),
            cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
                web_server_base.WebServerBase
            ),
            cv.Required(CONF_DISPLAY_ID): cv.use_id(ST7701S),
        }
    ).extend(cv.COMPONENT_SCHEMA),
    cv.only_with_esp_idf,
    socket.consume_sockets(2, "display_screenshot"),
)


async def to_code(config):
    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])
    var = cg.new_Pvariable(config[CONF_ID], base)
    await cg.register_component(var, config)
    display = await cg.get_variable(config[CONF_DISPLAY_ID])
    cg.add(var.set_display(display))
