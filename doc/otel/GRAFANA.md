<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Observability with Grafana</h3>

<p align="center">
  <em>Reference dashboards for traces, metrics and logs</em><br>
  <strong>Type</strong> · How-to &nbsp;|&nbsp; <strong>Audience</strong> · Developers &amp; operators
</p>

---

## Demo

<div align="center">

![Grafana Observability](grafana_demo.gif)

</div>

## Reference implementation

The reference implementation of Grafana observability lives in the
`otel/grafana/` directory: the OpenTelemetry Collector configuration
(`otel-config.yml`), Prometheus scrape config (`prometheus.yml`), Tempo trace
storage (`tempo.yml`) and Grafana datasources (`datasources.yml`).

These settings are consumed by the `compose-grafana.yml` file, which starts the
application with the full stack — OpenTelemetry Collector (OTLP on `:4317`/`:4318`),
Prometheus, Tempo, Loki and Grafana.

Run it and open the dashboards (see
[Running the Application](../DEV_GUIDE.md#running-the-application)):

```bash
docker compose -f compose-grafana.yml up --build
```

- Grafana UI: [http://localhost:3000](http://localhost:3000) — default credentials
  `admin` / `admin`
- The app's API: [http://localhost:18000/docs](http://localhost:18000/docs)

What to look at: per-request HTTP spans, nested LangChain LLM calls with token
usage, SQLAlchemy statements, and application logs in Loki. What gets instrumented
and why: the [Observability guide](../OTEL.md).

**Note:** this implementation is just a reference. For a real production scenario,
take privacy and security settings into account — authentication, authorization and
encryption.

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Observability](../OTEL.md) |
| ➡️ Next | [OpenSearch Dashboards example](OPENSEARCH.md) |
