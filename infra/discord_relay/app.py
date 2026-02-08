from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def _format_alerts(alerts):
    # Build a simple textual summary plus rich Discord embeds for each alert.
    lines = []
    embeds = []
    for a in alerts:
        status = a.get("status", "firing")
        labels = a.get("labels", {})
        ann = a.get("annotations", {})
        name = labels.get("alertname") or labels.get("alert") or "alert"
        sev = labels.get("severity", "info")
        summ = ann.get("summary") or ann.get("description") or ""
        startsAt = a.get("startsAt", "")
        lines.append(f"[{sev.upper()}] {name}: {summ} (since {startsAt})")

        # Compose fields for the embed (limit to relevant labels)
        fields = []
        # prefer strategyId or strategy if present
        if labels.get("strategyId"):
            fields.append({"name": "Strategy", "value": labels.get("strategyId"), "inline": True})
        if labels.get("symbol"):
            fields.append({"name": "Symbol", "value": labels.get("symbol"), "inline": True})
        fields.append({"name": "Severity", "value": sev, "inline": True})
        fields.append({"name": "Status", "value": status, "inline": True})
        if startsAt:
            fields.append({"name": "Started At", "value": startsAt, "inline": False})
        if summ:
            fields.append({"name": "Summary", "value": summ, "inline": False})

        # include some of the other labels (up to 4 shown)
        other_labels = []
        for k, v in labels.items():
            if k in ("alertname", "strategyId", "symbol", "severity"):
                continue
            other_labels.append(f"{k}={v}")
        if other_labels:
            fields.append({"name": "Labels", "value": ", ".join(other_labels[:10]), "inline": False})

        embed = {
            "title": f"{name} — {sev.upper()}",
            "description": summ or None,
            "color": 15158332 if sev.lower() in ("critical", "high", "danger") else 16776960 if sev.lower() in ("warning",) else 3066993,
            "fields": fields,
            "footer": {"text": "Alert from NunuIRL Prometheus/Alertmanager"},
        }
        # add quick links to Prometheus/Alertmanager (localhost-based)
        try:
            am_url = "http://localhost:9093"
            prom_url = "http://localhost:9090"
            embed["fields"].append({"name": "Links", "value": f"[Alertmanager]({am_url}) | [Prometheus]({prom_url})", "inline": False})
        except Exception:
            pass

        embeds.append(embed)

    return {"text": "\n".join(lines) or "Alert received.", "embeds": embeds}

@app.route("/alert", methods=["POST"])
def alert():
    if not DISCORD_WEBHOOK_URL:
        return jsonify({"error": "DISCORD_WEBHOOK_URL not set"}), 500
    payload = request.json or {}
    alerts = payload.get("alerts", [])
    formatted = _format_alerts(alerts)
    # If formatted is a dict with embeds, send as embed payload, otherwise plain content
    try:
        if isinstance(formatted, dict) and formatted.get("embeds"):
            body = {"content": formatted.get("text", "Alert received."), "embeds": formatted.get("embeds")[:10]}
        else:
            body = {"content": formatted}
        resp = requests.post(DISCORD_WEBHOOK_URL, json=body, timeout=10)
        return jsonify({"ok": True, "discord_status": resp.status_code, "body_sent": body}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081)
