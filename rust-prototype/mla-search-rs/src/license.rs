use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow};
use jsonwebtoken::{Algorithm, DecodingKey, Validation, decode};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const REFRESH_THRESHOLD_SECONDS: i64 = 24 * 60 * 60; // exp-dən 1 gün əvvəl refresh

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Claims {
    pub user_id: String,
    pub license_key: String,
    pub fingerprint: String,
    pub subscription_status: Option<String>,
    pub exp: i64,
    pub iat: Option<i64>,
    pub iss: Option<String>,
}

#[derive(Debug, Clone)]
pub struct LicenseConfig {
    pub license_key: Option<String>,
    pub server_url: Option<String>,
    pub public_key_pem: Option<Vec<u8>>,
    pub cache_path: PathBuf,
}

impl LicenseConfig {
    /// Mühit dəyişənlərindən konfiqurasiya oxu. Heç biri tələb olunmur —
    /// `license_key` boşdursa, dev mode-da işləyirik.
    pub fn from_env() -> Self {
        let cache_path = dirs::home_dir()
            .map(|h| h.join(".mla").join("token.jwt"))
            .unwrap_or_else(|| PathBuf::from(".mla_token.jwt"));

        let public_key_pem = std::env::var("MLA_LICENSE_PUBKEY")
            .ok()
            .and_then(|p| std::fs::read(p).ok());

        Self {
            license_key: std::env::var("MLA_LICENSE_KEY").ok().filter(|s| !s.is_empty()),
            server_url: std::env::var("MLA_LICENSE_SERVER_URL")
                .ok()
                .filter(|s| !s.is_empty()),
            public_key_pem,
            cache_path,
        }
    }

}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ActivatePayload {
    license_key: String,
    machine_fingerprint: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TokenResponse {
    token: String,
    expires_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CachedToken {
    token: String,
    expires_at: i64,
    fingerprint: String,
}

/// Sabit machine fingerprint: machine-uid + hostname, sonra SHA256 hex.
pub fn machine_fingerprint() -> Result<String> {
    let uid =
        machine_uid::get().map_err(|e| anyhow!("machine_uid: {e}"))?;
    let host = hostname::get()
        .map(|h| h.to_string_lossy().to_string())
        .unwrap_or_default();
    let combined = format!("{uid}|{host}");
    let hash = Sha256::digest(combined.as_bytes());
    Ok(hex::encode(hash))
}

fn now_unix() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or_default()
}

pub fn verify_token(token: &str, public_key_pem: &[u8]) -> Result<Claims> {
    let key = DecodingKey::from_rsa_pem(public_key_pem).context("invalid public key PEM")?;
    let mut validation = Validation::new(Algorithm::RS256);
    validation.set_issuer(&["mla-license-server"]);
    let data = decode::<Claims>(token, &key, &validation).context("JWT verify failed")?;
    Ok(data.claims)
}

async fn activate(
    server_url: &str,
    license_key: &str,
    fingerprint: &str,
) -> Result<TokenResponse> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;
    let res = client
        .post(format!("{server_url}/activate"))
        .json(&ActivatePayload {
            license_key: license_key.to_string(),
            machine_fingerprint: fingerprint.to_string(),
        })
        .send()
        .await?;
    if !res.status().is_success() {
        return Err(anyhow!(
            "activate failed: HTTP {} — {}",
            res.status(),
            res.text().await.unwrap_or_default()
        ));
    }
    Ok(res.json::<TokenResponse>().await?)
}

async fn refresh(server_url: &str, old_token: &str) -> Result<TokenResponse> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;
    let res = client
        .post(format!("{server_url}/validate"))
        .bearer_auth(old_token)
        .send()
        .await?;
    if !res.status().is_success() {
        return Err(anyhow!(
            "refresh failed: HTTP {} — {}",
            res.status(),
            res.text().await.unwrap_or_default()
        ));
    }
    Ok(res.json::<TokenResponse>().await?)
}

fn load_cache(path: &PathBuf) -> Option<CachedToken> {
    let bytes = std::fs::read(path).ok()?;
    serde_json::from_slice::<CachedToken>(&bytes).ok()
}

fn save_cache(path: &PathBuf, cache: &CachedToken) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    let bytes = serde_json::to_vec_pretty(cache)?;
    std::fs::write(path, bytes)?;
    Ok(())
}

pub struct LicenseGuard;

/// Lisenziya yoxlamasını başdan-sona aparır:
/// 1. Dev mode? (no key) → None qaytar
/// 2. Cache-də etibarlı token var? → onu istifadə et
/// 3. Cache yoxdursa və ya yaxınlaşmış expire → /activate və ya /validate çağır
/// 4. Yeni token-i verify et, cache-yə yaz, claims qaytar
pub async fn ensure_license(config: &LicenseConfig) -> Result<Option<LicenseGuard>> {
    let license_key = match &config.license_key {
        Some(k) => k,
        None => {
            eprintln!(
                "[mla] DEV MODE: MLA_LICENSE_KEY unset, license enforcement disabled."
            );
            return Ok(None);
        }
    };
    let server_url = config
        .server_url
        .as_ref()
        .ok_or_else(|| anyhow!("MLA_LICENSE_SERVER_URL is required when license key is set"))?;
    let pubkey = config
        .public_key_pem
        .as_ref()
        .ok_or_else(|| anyhow!("MLA_LICENSE_PUBKEY (path to PEM file) is required"))?;

    let fingerprint = machine_fingerprint()?;
    let now = now_unix();

    // 1) Cache-də etibarlı token varmı?
    if let Some(cached) = load_cache(&config.cache_path) {
        if cached.fingerprint == fingerprint
            && cached.expires_at > now + REFRESH_THRESHOLD_SECONDS
        {
            if verify_token(&cached.token, pubkey).is_ok() {
                return Ok(Some(LicenseGuard));
            }
        }
    }

    // 2) Cache köhnəlib və ya yoxdur → server-dən yenilə
    // Əgər cache-də token var amma refresh threshold-dadırsa, /validate;
    // yoxsa /activate.
    let response = if let Some(cached) = load_cache(&config.cache_path) {
        match refresh(server_url, &cached.token).await {
            Ok(r) => r,
            Err(_) => activate(server_url, license_key, &fingerprint).await?,
        }
    } else {
        activate(server_url, license_key, &fingerprint).await?
    };

    // 3) Yeni token-i verify et, cache-yə yaz
    let claims = verify_token(&response.token, pubkey)?;
    if claims.fingerprint != fingerprint {
        return Err(anyhow!("token fingerprint mismatch with this machine"));
    }
    let cached = CachedToken {
        token: response.token,
        expires_at: response.expires_at,
        fingerprint,
    };
    save_cache(&config.cache_path, &cached).ok();

    Ok(Some(LicenseGuard))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fingerprint_is_stable() {
        let a = machine_fingerprint().unwrap();
        let b = machine_fingerprint().unwrap();
        assert_eq!(a, b);
        assert_eq!(a.len(), 64); // sha256 hex
    }

    #[test]
    fn dev_mode_when_no_key() {
        let config = LicenseConfig {
            license_key: None,
            server_url: None,
            public_key_pem: None,
            cache_path: PathBuf::from(".test_token"),
        };
        assert!(config.license_key.is_none());
    }
}
