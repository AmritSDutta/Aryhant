export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("ok", { status: 200 });
    }
    const body = await request.text();
    let payload = {};
    try {
      payload = JSON.parse(body);
    } catch (err) {
      console.error("Invalid JSON body:", err);
      return new Response("bad json", { status: 400 });
    }
    if (payload.type === "url_verification") {
      console.log("Slack URL verification challenge answered.");
      return Response.json({ challenge: payload.challenge });
    }

    const qstashBase = (env.QSTASH_URL || "https://qstash.upstash.io").replace(/\/$/, "");
    const qstashUrl = `${qstashBase}/v2/publish/${env.CLOUD_RUN_WEBHOOK}`;

    console.log("Publishing to QStash URL:", qstashUrl);

    try {
      const res = await fetch(qstashUrl, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.QSTASH_TOKEN}`,
          "Content-Type": "application/json",
          "Upstash-Forward-X-Webhook-Secret": env.WEBHOOK_SHARED_SECRET || "",
          "Upstash-Retries": "5",
        },
        body,
      });

      const responseText = await res.text();
      console.log("QStash response:", res.status, responseText);

      if (!res.ok) {
        console.error(`QStash error [${res.status}]: ${responseText}`);
      }
    } catch (err) {
      console.error("Fetch to QStash failed:", err);
    }

    return new Response("ok", { status: 200 });
  },
};

