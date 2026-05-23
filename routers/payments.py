import stripe
import os
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database.database import get_db
from core.auth import get_current_user_from_token

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

router = APIRouter(prefix="/payments", tags=["payments"])
templates = Jinja2Templates(directory="templates")


def get_user(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_current_user_from_token(token, db)


@router.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    return templates.TemplateResponse("pricing.html", {"request": request, "user": user})


@router.post("/checkout")
async def create_checkout(
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login")

    body = await request.json()
    plan = body.get("plan")

    price_id = STRIPE_PRICE_BASIC if plan == "basic" else STRIPE_PRICE_PRO
    if not price_id:
        raise HTTPException(status_code=400, detail="Plan no válido o Stripe no configurado")

    try:
        session = stripe.checkout.Session.create(
            customer_email=user.email,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=f"{BASE_URL}/payments/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/payments/cancel",
            metadata={"user_id": str(user.id), "plan": plan},
            custom_text={
                "submit": {"message": "Al suscribirte aceptas los términos de RoadmapIA"}
            }
        )
        return JSONResponse({"url": session.url})
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    from database.models import User

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook inválido")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session["metadata"].get("user_id")
        plan = session["metadata"].get("plan")

        if user_id and plan:
            user = db.query(User).filter(User.id == int(user_id)).first()
            if user:
                user.plan = plan
                user.stripe_customer_id = session.get("customer")
                user.stripe_subscription_id = session.get("subscription")
                db.commit()

    elif event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        user = db.query(User).filter(
            User.stripe_subscription_id == sub["id"]
        ).first()
        if user:
            user.plan = "free"
            user.stripe_subscription_id = None
            db.commit()

    return JSONResponse({"status": "ok"})


@router.get("/success", response_class=HTMLResponse)
async def payment_success(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    return templates.TemplateResponse("payment_success.html", {"request": request, "user": user})


@router.get("/cancel", response_class=HTMLResponse)
async def payment_cancel(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    return templates.TemplateResponse("payment_cancel.html", {"request": request, "user": user})


@router.post("/cancelar-subscripcion")
async def cancelar_subscripcion(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    if not user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No tienes una suscripción activa")

    try:
        stripe.Subscription.delete(user.stripe_subscription_id)
        user.plan = "free"
        user.stripe_subscription_id = None
        db.commit()
        return JSONResponse({"ok": True, "mensaje": "Suscripción cancelada correctamente"})
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))
