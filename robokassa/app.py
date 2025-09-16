from flask import Flask, render_template, request, redirect, url_for, current_app, abort, jsonify
from config import Config
from robokassa_client import build_payment_url, verify_signature_from_result
from decimal import Decimal
from typing import Dict, Any, Optional
import logging

app = Flask(__name__)
app.config.from_object(Config)
logging.basicConfig(level=logging.INFO)

# --- Простая имитация "БД" для демонстрации ---
# В реальном приложении замените на вашу БД/ORM
ORDERS: Dict[str, Dict[str, Any]] = {
    # Пример:
    # "1001": {"id": "1001", "amount": Decimal("99.90"), "description": "Тестовый заказ", "status": "created", "shp": {"user": "123"}}
}

# --- Вспомогательные функции ---
class OrderNotFoundError(Exception):
    pass

def _get_order_data(order_id: str) -> Dict[str, Any]:
    order = ORDERS.get(str(order_id))
    if not order:
        raise OrderNotFoundError(f"Order {order_id} not found")
    return order

def _validate_order_parameters(order_id: str, amount: Decimal, description: str) -> None:
    if amount <= 0:
        raise ValueError("Amount must be positive")
    if not description:
        raise ValueError("Description required")

def _update_order_status(order_id: str, status: str, robokassa_data: Optional[Dict[str, Any]] = None) -> None:
    order = ORDERS.get(str(order_id))
    if not order:
        # для safety — создаём запись, но обычно это ошибка
        ORDERS[str(order_id)] = {"id": str(order_id), "amount": None, "description": None, "status": status}
        return
    order["status"] = status
    if robokassa_data:
        order.setdefault("robokassa", {}).update(robokassa_data)

# --- Роуты ---
@app.route("/", methods=["GET"])
def index():
    """
    Главная страница — показываем список тестовых заказов и форму для создания оплаты.
    """
    return render_template("index.html", orders=ORDERS)

@app.route("/create-order", methods=["POST"])
def create_order():
    """
    Удобно: быстрый эндпоинт, чтобы создать заказ (для примера).
    """
    amount = request.form.get("amount", "0").strip()
    description = request.form.get("description", "Заказ").strip()
    order_id = request.form.get("order_id") or str(len(ORDERS) + 1000)
    try:
        amount_dec = Decimal(amount)
    except Exception:
        return "Некорректная сумма", 400
    ORDERS[str(order_id)] = {"id": str(order_id), "amount": amount_dec, "description": description, "status": "created", "shp": {"user": "demo"}}
    return redirect(url_for("index"))

@app.route("/create-payment", methods=["POST"])
def create_payment():
    """
    Создаёт страницу оплаты (редиректит на Робокассу).
    """
    order_id = request.form.get("order_id")
    if not order_id:
        return "order_id required", 400
    try:
        order = _get_order_data(order_id)
    except OrderNotFoundError:
        return "Order not found", 404

    amount = order.get("amount")
    description = order.get("description", "")
    shp = order.get("shp", {})

    try:
        _validate_order_parameters(order_id, Decimal(amount), description)
    except ValueError as e:
        return str(e), 400

    # Формируем URL для редиректа
    cfg = current_app.config
    url = build_payment_url(
        merchant_login=cfg["ROBOKASSA_MERCHANT_LOGIN"],
        password1=cfg["ROBOKASSA_PASSWORD1"],
        out_sum=str(amount),     # робокасса ожидает строку вида "99.90"
        inv_id=str(order_id),
        description=description,
        shp=shp,
        is_test=cfg["ROBOKASSA_TEST_MODE"],
    )

    # Обновим статус на "pending"
    _update_order_status(order_id, "pending")
    return redirect(url, code=302)

@app.route("/payment/success", methods=["GET"])
def payment_success():
    """
    Пользователь возвращается сюда по Success URL. Проверяем подпись (Password1) и показываем результат.
    """
    out_sum = request.args.get("OutSum", "")
    inv_id = request.args.get("InvId", "")
    signature = request.args.get("SignatureValue", "")
    # собираем shp_ параметры
    shp = {k[4:]: v for k, v in request.args.items() if k.startswith("Shp_")}

    # Проверка подписи: формула аналогична той, что использовалась при генерации (Password1)
    cfg = current_app.config
    # Для простоты пересоздадим строку и сверим хэш
    from robokassa_client import _md5_upper, _format_shp_part
    base = f"{cfg['ROBOKASSA_MERCHANT_LOGIN']}:{out_sum}:{inv_id}:{cfg['ROBOKASSA_PASSWORD1']}"
    shp_part = _format_shp_part(shp)
    if shp_part:
        base = base + ":" + shp_part
    expected = _md5_upper(base)

    if expected != (signature or "").upper():
        # подпись не совпала — возможно вмешательство
        return render_template("fail.html", error_message="Invalid signature", order_id=inv_id), 400

    # Показываем пользователю страницу успеха (но основной processing — в Result)
    try:
        order = _get_order_data(inv_id)
    except OrderNotFoundError:
        order = {"id": inv_id, "amount": out_sum, "description": None, "status": "unknown"}
    return render_template("success.html", order_id=inv_id, payment_data=order)

@app.route("/payment/fail", methods=["GET"])
def payment_fail():
    inv_id = request.args.get("InvId", "")
    return render_template("fail.html", error_message="Платёж отменён или не прошёл", order_id=inv_id)

@app.route("/payment/result", methods=["POST"])
def payment_result():
    """
    Robokassa POST'ит сюда данные в автоматическом режиме (Result URL).
    Проверяем подпись (Password2) и обновляем статус заказа.
    Возвращаем OK{InvId} при успехе.
    """
    out_sum = request.form.get("OutSum", "")
    inv_id = request.form.get("InvId") or request.form.get("InvId") or request.form.get("InvId")  # иногда InvId/InvId case issues
    signature = request.form.get("SignatureValue", "")
    # соберём все Shp_ параметры
    shp = {k[4:]: v for k, v in request.form.items() if k.startswith("Shp_")}

    cfg = current_app.config
    if not inv_id:
        return "InvId missing", 400

    valid = verify_signature_from_result(
        out_sum=out_sum,
        inv_id=inv_id,
        signature_value=signature,
        password2=cfg["ROBOKASSA_PASSWORD2"],
        shp=shp
    )

    if not valid:
        current_app.logger.warning("Invalid signature on Result: inv=%s", inv_id)
        return "Invalid signature", 400

    # Обновляем статус заказа (например, 'paid')
    _update_order_status(inv_id, "paid", robokassa_data={"OutSum": out_sum, "shp": shp})
    # Возвращаем подтверждение Robokassa
    return f"OK{inv_id}"

# --- Обработчики ошибок ---
@app.errorhandler(404)
def not_found_error(error):
    return render_template("fail.html", error_message="Страница не найдена", order_id=""), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template("fail.html", error_message="Внутренняя ошибка сервера", order_id=""), 500

class RobokassaAPIError(Exception):
    pass

@app.errorhandler(RobokassaAPIError)
def robokassa_error(error):
    return render_template("fail.html", error_message=str(error), order_id=""), 500

if __name__ == "__main__":
    # Пример тестовых данных
    ORDERS["1001"] = {"id": "1001", "amount": Decimal("123.45"), "description": "Тестовый заказ 1001", "status": "created", "shp": {"user": "42"}}
    app.run(debug=True)
