export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("ok", { status: 200 });
    }
    const url = new URL(request.url);
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

    // Route by pathname or payload type (Slack vs AgentMail)
    const isAgentMail =
      url.pathname.includes("agentmail") ||
      url.pathname.includes("communicate") ||
      (typeof payload.event_type === "string" && payload.event_type.startsWith("message."));
    console.log("isAgentMail: ", isAgentMail);

    const qstashBase = (env.QSTASH_URL || "https://qstash.upstash.io").replace(/\/$/, "");

    let target = env.CLOUD_RUN_WEBHOOK;
    if (isAgentMail) {
      if (env.CLOUD_RUN_COMMUNICATE_URL) {
        target = env.CLOUD_RUN_COMMUNICATE_URL;
      } else if (env.CLOUD_RUN_BASE_URL) {
        target = `${env.CLOUD_RUN_BASE_URL.replace(/\/$/, "")}/api/communicate`;
      } else if (env.CLOUD_RUN_WEBHOOK) {
        target = env.CLOUD_RUN_WEBHOOK.replace(/\/webhooks\/slack\/?$/, "/api/communicate");
      }
    }

    const qstashUrl = `${qstashBase}/v2/publish/${target}`;
    console.log("Publishing to QStash URL:", qstashUrl);

    try {
      const res = await fetch(qstashUrl, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.QSTASH_TOKEN}`,
          "Content-Type": "application/json",
          "Upstash-Forward-X-Webhook-Secret": env.ARYHANT_WEBHOOK_SHARED_SECRET || "",
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
