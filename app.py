"""app.py

Main entry point for FoodVibes2024 webapi

20240301 Cyrus Kasra -- v-cyruskasra@microsoft.com -- Initial release

Returns:
    _type_: None
"""

import logging
from fastapi import Request
import uvicorn
from fastapi.responses import RedirectResponse

from api.common.config import logger
from api.common.fv_logging import setup_logger, setup_logger_level

setup_logger(
    logger, log_level=logging.WARNING
)  # Set up logging first in order to log any errors in the following imports

import api.adma  # noqa: F401
import api.constants  # noqa: F401
import api.farmvibes  # noqa: F401
import api.images  # noqa: F401
import api.sc_user  # noqa: F401
import api.sc_group  # noqa: F401
import api.sc_circle  # noqa: F401
import api.geotrack  # noqa: F401
import api.product  # noqa: F401
import api.tracking_products  # noqa: F401

from api.common.types import config
from api.common.access_check import access_check

setup_logger_level(logger, logging.INFO)
logger.info("started")

app = config.app  # Make app globally available


@config.app.get("/", include_in_schema=False)
def hello():
    """Default endpoint -- redirects to Swagger page for API testing"""

    return RedirectResponse("/docs")


@config.app.get("/map_key")
@access_check(check_for_roles=True)
async def map_key(request: Request):
    """Map Key Endpoint -- Fetches Map Key from Azure Key Value"""

    return config.maps_api_key


if __name__ == "__main__":
    uvicorn.run(config.app, port=7478, host="0.0.0.0")
