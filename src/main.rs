//! The Margin — local server.
//!
//! Serves index.html and proxies /api/sample to the Anthropic messages
//! endpoint, passing the SSE stream straight through so the page renders
//! prose as it is written.
//!
//!     export ANTHROPIC_API_KEY=sk-ant-...
//!     cargo run --release          # http://127.0.0.1:7878

use axum::{
    body::Body,
    extract::State,
    http::{header, HeaderMap, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::json;
use std::{env, net::SocketAddr, sync::Arc};

const API: &str = "https://api.anthropic.com/v1/messages";

#[derive(Clone)]
struct App {
    key: String,
    client: reqwest::Client,
    max_tokens: u32,
    quick: String,
    considered: String,
    complex: String,
}

impl App {
    fn model(&self, tier: Option<&str>) -> &str {
        match tier {
            Some("quick") => &self.quick,
            Some("complex") => &self.complex,
            _ => &self.considered,
        }
    }
}

#[derive(Deserialize)]
struct SampleReq {
    messages: Vec<serde_json::Value>,
    #[serde(default)]
    tier: Option<String>,
}

async fn index() -> Response {
    match tokio::fs::read_to_string("index.html").await {
        Ok(s) => Html(s).into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("index.html is missing — run patch.py first ({e})"),
        )
            .into_response(),
    }
}

async fn sample(State(app): State<Arc<App>>, Json(req): Json<SampleReq>) -> Response {
    if req.messages.is_empty() {
        return (StatusCode::BAD_REQUEST, "no messages").into_response();
    }

    let payload = json!({
        "model": app.model(req.tier.as_deref()),
        "max_tokens": app.max_tokens,
        "stream": true,
        "messages": req.messages,
    });

    // Console keys authenticate with x-api-key; OAuth access tokens
    // (sk-ant-oat..., the kind Claude Code issues) need a bearer header and are
    // rejected outright by x-api-key. Pick by prefix.
    let mut builder = app
        .client
        .post(API)
        .header("anthropic-version", "2023-06-01")
        .header(header::CONTENT_TYPE, "application/json");
    builder = if app.key.starts_with("sk-ant-oat") {
        builder.header(header::AUTHORIZATION, format!("Bearer {}", app.key))
    } else {
        builder.header("x-api-key", &app.key)
    };

    let upstream = builder.json(&payload).send().await;

    match upstream {
        Err(e) => (StatusCode::BAD_GATEWAY, format!("upstream unreachable: {e}")).into_response(),

        Ok(r) if !r.status().is_success() => {
            let code = StatusCode::from_u16(r.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
            let detail = r.text().await.unwrap_or_default();
            (code, detail.chars().take(600).collect::<String>()).into_response()
        }

        Ok(r) => {
            let mut headers = HeaderMap::new();
            headers.insert(header::CONTENT_TYPE, "text/event-stream".parse().unwrap());
            headers.insert(header::CACHE_CONTROL, "no-cache".parse().unwrap());
            (headers, Body::from_stream(r.bytes_stream())).into_response()
        }
    }
}

fn model_env(var: &str, fallback: &str) -> String {
    env::var(var).unwrap_or_else(|_| fallback.to_string())
}

#[tokio::main]
async fn main() {
    let key = env::var("ANTHROPIC_API_KEY").unwrap_or_default();
    if key.is_empty() {
        eprintln!("! ANTHROPIC_API_KEY is not set — the page will load but no turn will write.");
        eprintln!("  export ANTHROPIC_API_KEY=sk-ant-...\n");
    }

    let app = Arc::new(App {
        key,
        client: reqwest::Client::new(),
        max_tokens: env::var("MARGIN_MAX_TOKENS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(8192),
        quick: model_env("MARGIN_QUICK", "claude-haiku-4-5-20251001"),
        considered: model_env("MARGIN_DEFAULT", "claude-sonnet-5"),
        complex: model_env("MARGIN_COMPLEX", "claude-opus-5"),
    });

    let port: u16 = env::var("MARGIN_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(7878);
    let host = env::var("MARGIN_HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let octets: Vec<u8> = host.split('.').filter_map(|s| s.parse().ok()).collect();
    let ip = if octets.len() == 4 { [octets[0], octets[1], octets[2], octets[3]] } else { [127, 0, 0, 1] };
    if ip != [127, 0, 0, 1] {
        println!("! Listening on {host} — anyone who can reach this machine can play,");
        println!("  and every turn they take spends YOUR key. Keep it to your own network.\n");
    }
    let addr = SocketAddr::from((ip, port));

    println!("The Margin  ->  http://{addr}");
    println!("  brisk      {}", app.quick);
    println!("  considered {}", app.considered);
    println!("  outline    {}", app.complex);
    println!("  ctrl-c to stop\n");

    let router = Router::new()
        .route("/", get(index))
        .route("/index.html", get(index))
        .route("/api/sample", post(sample))
        .with_state(app);

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .unwrap_or_else(|e| panic!("cannot bind {addr}: {e}"));
    axum::serve(listener, router).await.unwrap();
}
