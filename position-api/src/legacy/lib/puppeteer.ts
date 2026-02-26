const puppeteer = require("puppeteer-extra");
const StealthPlugin = require("puppeteer-extra-plugin-stealth");

// Use stealth plugin to avoid Cloudflare/bot detection
puppeteer.use(StealthPlugin());

// Modern Chrome UA — must match a real browser
const CHROME_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

/**
 * Wait until a Cloudflare challenge page resolves.
 * Returns true if the page content changed away from challenge.
 */
const waitForCloudflareClearance = async (page, maxWaitMs = 30000) => {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    try {
      const title = await page.title();
      const bodyText = await page.evaluate(
        () => document.body?.innerText?.slice(0, 200) || ""
      );
      // Cloudflare challenge indicators
      if (
        title.includes("Just a moment") ||
        bodyText.includes("Just a moment") ||
        bodyText.includes("Checking your browser") ||
        bodyText.includes("Enable JavaScript")
      ) {
        console.log("[puppeteer] Cloudflare challenge active — waiting...");
        await new Promise((r) => setTimeout(r, 3000));
        continue;
      }
      // Challenge resolved
      return true;
    } catch {
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  return false;
};

const scrapeJsonFromResponse = async (options, cb) => {
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: "new",
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--window-size=1920,1080",
        "--lang=en-US,en",
      ],
    });

    const page = await browser.newPage();

    // Must set UA before any navigation
    await page.setUserAgent(CHROME_UA);
    await page.setViewport({ width: 1920, height: 1080 });

    // Anti-detection overrides
    await page.evaluateOnNewDocument(() => {
      Object.defineProperty(navigator, "webdriver", { get: () => false });
      Object.defineProperty(navigator, "languages", {
        get: () => ["en-US", "en"],
      });
      Object.defineProperty(navigator, "plugins", {
        get: () => [1, 2, 3, 4, 5],
      });
      (window as any).chrome = { runtime: {} };
    });

    await page.setExtraHTTPHeaders({
      "x-requested-with": "XMLHttpRequest",
      referer: options.referer,
      "accept-language": "en-US,en;q=0.9",
      accept: "application/json, text/javascript, */*; q=0.01",
      ...options.extraHeaders,
    });

    // Track JSON response
    let resolved = false;
    let jsonData: any = null;

    page.on("requestfinished", async (request) => {
      if (resolved) return;
      const resUrl = request.url();
      if (resUrl.indexOf(options.responseSelector) !== -1) {
        const response = request.response();
        try {
          const contentType = response.headers()["content-type"] || "";
          if (!contentType.includes("json") && !contentType.includes("javascript")) {
            return; // Skip non-JSON (CSS, HTML, etc.)
          }
          const text = await response.text();
          if (text.startsWith("<!DOCTYPE") || text.startsWith("<html")) {
            return; // HTML response — blocked
          }
          jsonData = JSON.parse(text);
          console.log("[puppeteer] JSON response captured from:", resUrl.slice(0, 100));
          resolved = true;
        } catch (err) {
          // Ignore parse errors on this request, another one may succeed
        }
      }
    });

    page.on("request", (interceptedRequest) => {
      const reqUrl = interceptedRequest.url();
      if (
        !reqUrl.includes("cdn-cgi") &&
        !reqUrl.includes(".css") &&
        !reqUrl.includes(".png") &&
        !reqUrl.includes(".svg") &&
        !reqUrl.includes("favicon")
      ) {
        console.log("[puppeteer] Request:", reqUrl.slice(0, 120));
      }
    });

    // Navigate — Cloudflare may show a challenge first
    console.log("[puppeteer] Navigating to:", options.url.slice(0, 100));
    await page.goto(options.url, {
      waitUntil: "networkidle2",
      timeout: 60000,
    });

    // If we got data during navigation, great
    if (resolved) {
      cb(jsonData);
      return;
    }

    // Check for Cloudflare challenge and wait
    const cleared = await waitForCloudflareClearance(page, 30000);
    if (cleared && !resolved) {
      // After challenge clears, the browser should redirect to the real page
      // Wait for network to settle after the redirect
      console.log("[puppeteer] Challenge may have cleared — waiting for data...");
      await new Promise((r) => setTimeout(r, 5000));
    }

    if (resolved) {
      cb(jsonData);
    } else {
      console.warn("[puppeteer] No JSON data received after challenge wait");
      cb(null);
    }
  } catch (err) {
    console.error("[puppeteer] Scrape error:", (err as Error).message);
    cb(null);
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch {
        // ignore
      }
    }
  }
};

module.exports = {
  fetch: scrapeJsonFromResponse,
};
