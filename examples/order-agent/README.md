# Order Agent Example

The runnable application lives in `examples/order_agent/app.py` so it can be
imported as a Python package. Start it from the repository root with:

```powershell
uvicorn examples.order_agent.app:app --port 8103
```

It implements the workbench `POST /run` protocol and has deterministic paths
for order lookup, a permitted cancellation, a prohibited post-shipment
cancellation, a refund only after delivery, and a missing order ID.
