<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Observability with OpenSearch Dashboards</h3>

<p align="center">
  <em>Reference dashboards for traces, metrics and logs</em><br>
  <strong>Type</strong> · How-to &nbsp;|&nbsp; <strong>Audience</strong> · Developers &amp; operators
</p>

---

## Demo

<div align="center">

![OpenSearch Dashboards Observability](opensearch_dashboards_demo.gif)

</div>

## Reference implementation

The reference implementation of OpenSearch Dashboards observability lives in the
`otel/opensearch/` directory: the OpenTelemetry Collector configuration
(`otel-config.yml`) plus Data Prepper pipelines and SS4O (AWS Solutions for
Observability) index templates.

These settings are consumed by the `compose-opensearch.yml` file, which starts the
application with the full stack — OpenTelemetry Collector, Data Prepper,
OpenSearch and OpenSearch Dashboards.

Run it and open the dashboards (see
[Running the Application](../DEV_GUIDE.md#running-the-application)):

```bash
docker compose -f compose-opensearch.yml up --build
```

- OpenSearch Dashboards: [http://localhost:5601](http://localhost:5601)
- The app's API: [http://localhost:18000/docs](http://localhost:18000/docs)

What to look at: OpenTelemetry traces of agent interactions (HTTP → LLM calls →
database), service metrics, and logs routed through the Data Prepper pipelines.
What gets instrumented and why: the [Observability guide](../OTEL.md).

**Note:** this implementation is just a reference. For a real production scenario,
take privacy and security settings into account — authentication, authorization and
encryption.

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Grafana example](GRAFANA.md) |
