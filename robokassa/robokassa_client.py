import hashlib
from urllib.parse import urlencode, quote_plus
from typing import Dict, Optional, Tuple

ROBOKASSA_GATEWAY = "https://auth.robokassa.ru/Merchant/Index.aspx"

def _format_shp_part(shp: Dict[str, str]) -> str:
    """
    Формирует часть строки для подписи из shp-параметров.
    Требование Robokassa: Shp-параметры в формате `Shp_key=value`, в алфавитном порядке ключей.
    """
    if not shp:
        return ""
    items = sorted(shp.items(), key=lambda x: x[0])
    return ":".join(f"Shp_{k}={v}" for k, v in items)

def _md5_upper(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest().upper()

def build_payment_url(
    merchant_login: str,
    password1: str,
    out_sum: str,
    inv_id: str,
    description: Optional[str] = None,
    shp: Optional[Dict[str, str]] = None,
    is_test: bool = False,
    extra_params: Optional[Dict[str, str]] = None
) -> str:
    """
    Возвращает URL для перенаправления пользователя на Робокассу.
    Формула подписи: MerchantLogin:OutSum:InvId:Password1[:Shp_key=value:...]
    (Shp-параметры добавляются в алфавитном порядке ключей).
    """
    shp = shp or {}
    base_for_sign = f"{merchant_login}:{out_sum}:{inv_id}:{password1}"
    shp_part = _format_shp_part(shp)
    if shp_part:
        base_for_sign = base_for_sign + ":" + shp_part
    signature = _md5_upper(base_for_sign)

    params = {
        "MerchantLogin": merchant_login,
        "OutSum": out_sum,
        "InvId": inv_id,
        "SignatureValue": signature,
    }
    if description:
        params["Description"] = description
    if is_test:
        params["IsTest"] = "1"
    # добавить shp_ параметры в GET (Robokassa ожидает именно такие имена)
    for k, v in shp.items():
        params[f"Shp_{k}"] = v

    if extra_params:
        params.update(extra_params)

    query = urlencode(params, quote_via=quote_plus)
    return f"{ROBOKASSA_GATEWAY}?{query}"

def verify_signature_from_result(
    out_sum: str,
    inv_id: str,
    signature_value: str,
    password2: str,
    shp: Optional[Dict[str, str]] = None
) -> bool:
    """
    Проверка подписи при Result (используется Password2).
    Формула: OutSum:InvId:Password2[:Shp_key=value:...]
    signature_value в верхнем регистре.
    """
    shp = shp or {}
    base = f"{out_sum}:{inv_id}:{password2}"
    shp_part = _format_shp_part(shp)
    if shp_part:
        base = base + ":" + shp_part
    expected = _md5_upper(base)
    return expected == signature_value.upper()
