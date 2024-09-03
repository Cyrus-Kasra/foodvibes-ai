from http import HTTPStatus
import time
from typing import Tuple
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from fastapi import Request, HTTPException, status
from functools import wraps
from api.common.database.common_utils import get_session
from api.common.database.table_sc_user import fetch_sc_user_rows
from api.common.roles_permissions import is_op_allowed
from api.common.types import (
    CommonError,
    CommonQueryParams,
    CommonQueryResponse,
    CommonQueryResponseMeta,
    config,
)
from api.common.config import logger
from api.common.fv_logging import setup_logger
from api.common.utils import convert_unix_timestamp_to_iso8601, is_production


def is_access_token_valid(client_id: str, access_token: str) -> Tuple[bool, str, str]:
    logger.info(f"Checking if access token is valid for client ID: {client_id}...")

    try:
        # Fetch public keys from Microsoft Entra ID
        jwks_url = "https://login.microsoftonline.com/common/discovery/keys"
        response = requests.get(jwks_url)

        if response.status_code != status.HTTP_200_OK:
            raise Exception(f"Failed to fetch JWKS from {jwks_url}")

        jwks = response.json()

        if not jwks.get("keys"):
            raise Exception("No keys found in the JWKS")

        # Decode the token headers to get the key ID (kid)
        token_headers = jwt.get_unverified_header(access_token)
        kid = token_headers.get("kid")

        if not kid:
            raise Exception("Key ID (kid) not found in the token headers")

        # Find the public key in the JWKS
        public_key = None

        for key in jwks["keys"]:
            if key["kid"] == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)  # type: ignore
                break

        # Convert the public key to PEM format
        rsa_pem_key_bytes = public_key.public_bytes(  # type: ignore
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Get algorithm from token header
        alg = jwt.get_unverified_header(access_token)["alg"]

        # Decode token
        decoded_token = jwt.decode(
            access_token,
            key=rsa_pem_key_bytes,
            algorithms=[alg],
            verify=True,
            audience=[client_id],
            options={"verify_signature": False},
        )

        logger.info(f"Decoded token name: {decoded_token.get('name')}")

        appid = decoded_token.get("appid")

        if appid is None:
            raise Exception("No appid found in the token")

        if client_id != appid:
            raise Exception("Client ID does not match appid")

        exp = decoded_token.get("exp")
        cur = int(time.time())

        logger.info(f"Token expiration: {convert_unix_timestamp_to_iso8601(exp)} {exp}")
        logger.info(f"Current time::::: {convert_unix_timestamp_to_iso8601(cur)} {cur}")

        # Check if the token has expired
        if exp and cur < exp:
            msg = "Token is valid"

            logger.info(msg)

            return True, msg, decoded_token.get("upn") or decoded_token.get("email")

        raise Exception("Token has expired")
    except Exception as e:
        msg = f"{e}"

        logger.error(msg)

        return False, msg, ""


def access_check(check_for_roles: bool = False):
    def decorator(func):
        @wraps(func)
        async def decorated_function(request: Request, *args, **kwargs):
            status_code = status.HTTP_403_FORBIDDEN

            try:
                logger.info(
                    f"Checking access for {func.__name__}(check_for_roles={check_for_roles})..."
                )

                authorization: str = request.headers.get("Authorization", "")

                if not authorization:
                    raise HTTPException(
                        status_code=status_code, detail="Authorization header missing"
                    )

                scheme, token = authorization.split()

                if scheme.lower() != "bearer":
                    raise HTTPException(
                        status_code=status_code, detail="Invalid or missing bearer scheme"
                    )

                is_valid, msg, user = is_access_token_valid(config.entra_id_client_id, token)

                if not is_valid:
                    raise HTTPException(status_code=status_code, detail=msg)

                if len(f'{user or ""}') == 0:
                    raise HTTPException(
                        status_code=status_code, detail="User not found in the token"
                    )

                if not is_production():
                    user_override = request.query_params.get("impersonated_user")

                    if len(f'{user_override or ""}') > 0:
                        user = user_override

                logger.info(f"Active user: {user}")

                if check_for_roles is True and "commons" in kwargs:
                    # Obtain user role(s) and permissions from db
                    with get_session() as db_session:
                        kwargs["commons"].impersonated_user = user
                        kwargs["commons"].db_session = db_session

                        commons_lookup: CommonQueryParams = CommonQueryParams()

                        commons_lookup.db_session = db_session

                        response: CommonQueryResponse = fetch_sc_user_rows(
                            commons_lookup, sc_user_id=f"{user}"
                        )

                        if response.error.error_level != CommonError.ErrorLevel.SUCCESS:
                            raise HTTPException(
                                status_code=status_code, detail=response.error.message
                            )

                        if len(response.data) == 0:
                            raise HTTPException(
                                status_code=status_code, detail="User not found in the database"
                            )

                        active_access_mask = response.data[0]["access_mask"]

                        if active_access_mask == 0:
                            raise HTTPException(
                                status_code=status_code,
                                detail="User does not have the required role to access this "
                                "resource (access_mask is 0)",
                            )

                        kwargs["commons"].active_access_mask = active_access_mask

                        if not is_op_allowed(func.__name__, kwargs["commons"], commons_lookup):
                            raise HTTPException(
                                status_code=status_code,
                                detail="User does not have the required role to access this "
                                "resource (2)",
                            )

                        logger.info(
                            f"Gate allowed {func.__name__}(check_for_roles={check_for_roles})"
                        )

                        resonse_fn = await func(request, *args, **kwargs)

                        if resonse_fn.error.error_level != CommonError.ErrorLevel.SUCCESS:
                            raise HTTPException(
                                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                                detail=resonse_fn.error.message,
                            )

                        return resonse_fn
                else:
                    return await func(request, *args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error in access_check for {func.__name__}(check_for_roles={check_for_roles}):"
                    f" {e}"
                )

                return CommonQueryResponse(
                    CommonError(error_level=CommonError.ErrorLevel.ERROR, code=1, msessage=str(e)),
                    CommonQueryResponseMeta(0, 0, CommonQueryParams()),
                    [],
                )

        return decorated_function

    return decorator


if __name__ == "__main__":
    setup_logger(logger)
    logger.info("Sample token validation test started")

    for token in [
        "eyJ0eXAiOiJKV1QiLCJub25jZSI6ImIxLTZoeWhDYmVyTkRkeHF3UkV4VFU2Qm9LNHV6YWUtQ05WSGRqSFY2WGciLC"
        "JhbGciOiJSUzI1NiIsIng1dCI6Ik1HTHFqOThWTkxvWGFGZnBKQ0JwZ0I0SmFLcyIsImtpZCI6Ik1HTHFqOThWTkxv"
        "WGFGZnBKQ0JwZ0I0SmFLcyJ9.eyJhdWQiOiIwMDAwMDAwMy0wMDAwLTAwMDAtYzAwMC0wMDAwMDAwMDAwMDAiLCJpc"
        "3MiOiJodHRwczovL3N0cy53aW5kb3dzLm5ldC83MmY5ODhiZi04NmYxLTQxYWYtOTFhYi0yZDdjZDAxMWRiNDcvIiw"
        "iaWF0IjoxNzIxNTAzODE2LCJuYmYiOjE3MjE1MDM4MTYsImV4cCI6MTcyMTUwODU5NSwiYWNjdCI6MCwiYWNyIjoiM"
        "SIsImFjcnMiOlsidXJuOnVzZXI6cmVnaXN0ZXJzZWN1cml0eWluZm8iLCJjMiIsImMzIiwiYzEwIl0sImFpbyI6IkF"
        "UUUJ5LzRYQUFBQUNwbUwvKzJmbEd6aFV6RmJtM2tjeWl5bmpvZi9nMXlZNkc2NVkyK09sODZTaE5yVzBXR2JCNW9ib"
        "ERXR29SKytFQWM4MjY4R0VCN0JTTndsUkFmZE45L0Q0N3pQSU1Fb2VnRUsrNEdWTHpRa0UxdUhaU2tLdFUwN2JkY0J"
        "5M0hVKy94SjR1c2pwRklEK1JzQ2FvVjRlcWRoZHpIT2x1UGtQMmljRkY0cVByRWhwQlVCajJZUk05TndOTmdhcnJQd"
        "FhMdFNrZEtqMHBacXJsbk1mQUlJRURKWFZrT3prZmRUb3NmM3AvbzdjTTA3cTg0Vjg4b0llTkFkbDF2cGdlQkdNODV"
        "rSWZxbEEzbXR3bjNkb1FybjZaSlJlUUhHTllVZkt5R1lTekJpeWNlZkVvdjVlYjE0dE5oeW1DSmtJZ2RTdVYxdHYzY"
        "XlKUlRNdkNmYVlLWFNaYk5hdlprZzhBR1ZJVGJQelR2Z3J2RlIzN2hZWnNEL1ZOVm4vcjZvNnVxekpNRWh1MXZsU0N"
        "XdWVPdzh4emtTMlE9PSIsImFtciI6WyJyc2EiLCJtZmEiXSwiYXBwX2Rpc3BsYXluYW1lIjoiTVNSIEZvb2RWaWJlc"
        "yIsImFwcGlkIjoiYTQ2Y2VkYzUtMGYzNC00N2EwLWFlMTMtMGZkZjc4MjFmMDUxIiwiYXBwaWRhY3IiOiIwIiwiY29"
        "udHJvbHMiOlsiYXBwX3JlcyJdLCJjb250cm9sc19hdWRzIjpbImE0NmNlZGM1LTBmMzQtNDdhMC1hZTEzLTBmZGY3O"
        "DIxZjA1MSJdLCJkZXZpY2VpZCI6ImI1NDc4YTQ4LTk2Y2QtNGU3ZS1hYWM3LWUyZjA2YjQ4OGUwMCIsImZhbWlseV9"
        "uYW1lIjoiS2FzcmEgKFNDLUFMVCkiLCJnaXZlbl9uYW1lIjoiQ3lydXMiLCJpZHR5cCI6InVzZXIiLCJpbl9jb3JwI"
        "joidHJ1ZSIsImlwYWRkciI6IjcyLjIxOS4xODIuMTc4IiwibmFtZSI6IkN5cnVzIEthc3JhIChOT04gRUEgU0MgQUx"
        "UKSIsIm9pZCI6IjM2ODZkZmU0LWFmZjQtNDkyZi04MjU0LWI5Njk2ZjQzY2NiMSIsIm9ucHJlbV9zaWQiOiJTLTEtN"
        "S0yMS0xMjQ1MjUwOTUtNzA4MjU5NjM3LTE1NDMxMTkwMjEtMjIwOTE0MSIsInBsYXRmIjoiMyIsInB1aWQiOiIxMDA"
        "zMjAwMzhERkNCMDlEIiwicmgiOiIwLkFSb0F2NGo1Y3ZHR3IwR1JxeTE4MEJIYlJ3TUFBQUFBQUFBQXdBQUFBQUFBQ"
        "UFBYUFGTS4iLCJzY3AiOiJvcGVuaWQgcHJvZmlsZSBVc2VyLlJlYWQgZW1haWwiLCJzaWduaW5fc3RhdGUiOlsiZHZ"
        "jX21uZ2QiLCJkdmNfY21wIiwia21zaSJdLCJzdWIiOiJZLVh2dDZhSGN2V041TExBcWhGQ2NuMGQxVG9vRy1PTS1WR"
        "HdWLUt1alZNIiwidGVuYW50X3JlZ2lvbl9zY29wZSI6IldXIiwidGlkIjoiNzJmOTg4YmYtODZmMS00MWFmLTkxYWI"
        "tMmQ3Y2QwMTFkYjQ3IiwidW5pcXVlX25hbWUiOiJzYy12aG40MTYzNjBAbWljcm9zb2Z0LmNvbSIsInVwbiI6InNjL"
        "XZobjQxNjM2MEBtaWNyb3NvZnQuY29tIiwidXRpIjoiSlRRSG5LT3V3RXFPU1lXNE9rcFdBQSIsInZlciI6IjEuMCI"
        "sIndpZHMiOlsiYjc5ZmJmNGQtM2VmOS00Njg5LTgxNDMtNzZiMTk0ZTg1NTA5Il0sInhtc19pZHJlbCI6IjggMSIsI"
        "nhtc19zdCI6eyJzdWIiOiJfZTY3Q3JPNVE0TFZlVGRFYW5Mdnk4cmZhVmhFZHJXMUhxZkJFTVUySkgwIn0sInhtc19"
        "0Y2R0IjoxMjg5MjQxNTQ3fQ.UlWPmcFlQvYquDHIbUJBykIPjo2ATw4JeV2SszHBK1_Zo-eT_ioi2MT1rYCYDZQrv2"
        "DXRfruO5nMWcneA7CQ0F-J70tSKQ8xFUpR0465m1XqN7wpzGg4e0fwy3WQX_8HgTAGOvGRSa0gsrP6LV4QelLfw18t"
        "mk7fOhdDBDTtwhnaoMVZafpzu0vCqEjXndbwIxHi46wyXnZUGZnCilNE2UXqY6pqUNwmRVv8dJjW-mIzk40A6zmeTs"
        "6XAxNmB8XWShh1L6YBbtNuvv6GBNIxTGRBcybr9SdZyGOAXYy7R0KxtU-2DRRSp2828n1IVFYZ_iTAlZDUh-iVC1ES"
        "6BA2Fg",
        "xeyJ0eXAiOiJKV1QiLCJub25jZSI6IjZWUk5WcVd1d0JZdndlYzVGUDUzeXAweXRURmRqWTZtRlpBTktqSUpvSTgiL"
        "CJhbGciOiJSUzI1NiIsIng1dCI6Ik1HTHFqOThWTkxvWGFGZnBKQ0JwZ0I0SmFLcyIsImtpZCI6Ik1HTHFqOThWTkx"
        "vWGFGZnBKQ0JwZ0I0SmFLcyJ9.eyJhdWQiOiIwMDAwMDAwMy0wMDAwLTAwMDAtYzAwMC0wMDAwMDAwMDAwMDAiLCJp"
        "c3MiOiJodHRwczovL3N0cy53aW5kb3dzLm5ldC83MmY5ODhiZi04NmYxLTQxYWYtOTFhYi0yZDdjZDAxMWRiNDcvIi"
        "wiaWF0IjoxNzIxNDUxOTE5LCJuYmYiOjE3MjE0NTE5MTksImV4cCI6MTcyMTQ1NzA3MSwiYWNjdCI6MCwiYWNyIjoi"
        "MSIsImFjcnMiOlsidXJuOnVzZXI6cmVnaXN0ZXJzZWN1cml0eWluZm8iLCJjMTAiXSwiYWlvIjoiQVlRQWUvOFhBQU"
        "FBQ0ZPaHY2Z3kyQzQ4R0M4U253Vlg5dDFpeWVEcVhsSjdpb3JrUEJjY2dKR1dYeTZGUDZ2d1FyQXYwbUlmRmpXQnJY"
        "Qm1DdFVLdmg5UklpM1ExUjZTRXY4Y1hVNkFZdk8vSktneVlLTXc0Y2hCT2I2Wm1uQldGNVBvOENOVDRTVmxLSjNSWU"
        "5zNUoyR3VFSlUybnpYWVJXY2NVYlhjWGVLNkVxeER3NDVGeG1JPSIsImFtciI6WyJyc2EiLCJtZmEiXSwiYXBwX2Rp"
        "c3BsYXluYW1lIjoiTVNSIEZvb2RWaWJlcyIsImFwcGlkIjoiYTQ2Y2VkYzUtMGYzNC00N2EwLWFlMTMtMGZkZjc4Mj"
        "FmMDUxIiwiYXBwaWRhY3IiOiIwIiwiY29udHJvbHMiOlsiYXBwX3JlcyJdLCJjb250cm9sc19hdWRzIjpbImE0NmNl"
        "ZGM1LTBmMzQtNDdhMC1hZTEzLTBmZGY3ODIxZjA1MSJdLCJkZXZpY2VpZCI6ImI1NDc4YTQ4LTk2Y2QtNGU3ZS1hYW"
        "M3LWUyZjA2YjQ4OGUwMCIsImZhbWlseV9uYW1lIjoiS2FzcmEiLCJnaXZlbl9uYW1lIjoiQ3lydXMiLCJpZHR5cCI6"
        "InVzZXIiLCJpcGFkZHIiOiI3Mi4yMTkuMTgyLjE3OCIsIm5hbWUiOiJDeXJ1cyBLYXNyYSAoU29waHVzIEl0IFNvbH"
        "V0aW9ucyBMTEMpIiwib2lkIjoiMzViNGYzM2QtMmZmNC00NzA1LThjM2YtOTE3OTAwYmUwNjNiIiwib25wcmVtX3Np"
        "ZCI6IlMtMS01LTIxLTIxMjc1MjExODQtMTYwNDAxMjkyMC0xODg3OTI3NTI3LTc0OTc5NTQ2IiwicGxhdGYiOiIzIi"
        "wicHVpZCI6IjEwMDMyMDAzNTM1Nzg5RjgiLCJyaCI6IjAuQVJvQXY0ajVjdkdHcjBHUnF5MTgwQkhiUndNQUFBQUFB"
        "QUFBd0FBQUFBQUFBQUFhQU04LiIsInNjcCI6Im9wZW5pZCBwcm9maWxlIFVzZXIuUmVhZCBlbWFpbCIsInNpZ25pbl"
        "9zdGF0ZSI6WyJkdmNfbW5nZCIsImR2Y19jbXAiLCJrbXNpIl0sInN1YiI6IkhoVF9nVmpsVUwwTE1sRGE5WWJaMERR"
        "alE3X0pjUFV1bXRNdEpMRHBISjgiLCJ0ZW5hbnRfcmVnaW9uX3Njb3BlIjoiV1ciLCJ0aWQiOiI3MmY5ODhiZi04Nm"
        "YxLTQxYWYtOTFhYi0yZDdjZDAxMWRiNDciLCJ1bmlxdWVfbmFtZSI6InYtY3lydXNrYXNyYUBtaWNyb3NvZnQuY29t"
        "IiwidXBuIjoidi1jeXJ1c2thc3JhQG1pY3Jvc29mdC5jb20iLCJ1dGkiOiI0QXpRQmRWeU9rS2lTZVBUMFVRR0FBIi"
        "widmVyIjoiMS4wIiwid2lkcyI6WyJiNzlmYmY0ZC0zZWY5LTQ2ODktODE0My03NmIxOTRlODU1MDkiXSwieG1zX2lk"
        "cmVsIjoiMSAxNiIsInhtc19zdCI6eyJzdWIiOiJHUURoXzhiMFVvcGFQVTdwVTk0XzFSTlBfVmZhWEFHUTREQkJYLU"
        "NEaUc0In0sInhtc190Y2R0IjoxMjg5MjQxNTQ3fQ.KBhlcwApnOPktKMpl2IaLzDT8j491WianmWEVHzDyzfdkkyDn"
        "ihSvTJSnaegaXUeXCskwMTNjfFKH7LuSBAys-e44tuV3I9K3MjNzkDVZcLYheZpmF2AvmJngqw5cWWOZcWgZz-dmlr"
        "fne7c8MCfGX9y5NrKh0qniF6nHfdYG2j9Hq43j0gj9Zcx1OB0rXaVwDckTdV_S1LxVH9b5yZ3YQJdKYKlOaa8cJcvS"
        "l6GdQhqA0BtETQoBvs5iwqmpnIbAzTRvZEVQMnSxNnWCBua0zrY_7iylBrNukAJB3v-IXVL582GT79oKVGF1MLWshw"
        "SQYqQMYT7Cf9zS_omRXVJnQ",
    ]:
        is_valid, msg, user = is_access_token_valid(config.entra_id_client_id, token)

        (logger.info if is_valid else logger.error)(f"valid token={is_valid} {msg} {user}")

    logger.info("Sample token validation test completed")
