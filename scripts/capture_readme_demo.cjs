#!/usr/bin/env node

const fs = require("node:fs/promises");
const path = require("node:path");

const { chromium } = require("playwright");

function getArg(flag, fallback) {
    const index = process.argv.indexOf(flag);
    if (index === -1 || index === process.argv.length - 1) {
        return fallback;
    }
    return process.argv[index + 1];
}

async function ensureDir(dirPath) {
    await fs.mkdir(dirPath, { recursive: true });
}

async function holdFrames(page, framesDir, state) {
    const { count, prefix, nextIndexRef } = state;
    for (let i = 0; i < count; i += 1) {
        const filename = `${String(nextIndexRef.value).padStart(3, "0")}-${prefix}.png`;
        await page.screenshot({
            path: path.join(framesDir, filename),
            type: "png",
        });
        nextIndexRef.value += 1;
    }
}

async function waitForAnalytics(page) {
    await page.waitForFunction(() => {
        const ids = [
            "budget-variance-container",
            "monthly-overview-container",
            "top-transactions-container",
            "category-breakdown-container",
            "savings-tracking-container",
            "yoy-comparison-container",
        ];
        return ids.every((id) => {
            const element = document.getElementById(id);
            return element && !/Loading/i.test(element.textContent || "");
        });
    });
    await page.waitForTimeout(1500);
}

async function main() {
    const baseUrl = getArg("--base-url", "http://127.0.0.1:8010");
    const outputDir = path.resolve(getArg("--output-dir", "docs/media/.raw"));
    const demoCsvPath = path.resolve(getArg("--demo-csv", "docs/media/demo-import.csv"));
    const framesDir = path.join(outputDir, "gif-frames");
    const videoDir = path.join(outputDir, "video");

    await ensureDir(outputDir);
    await ensureDir(framesDir);
    await ensureDir(videoDir);

    const browser = await chromium.launch({
        headless: true,
    });

    const context = await browser.newContext({
        viewport: { width: 1440, height: 1024 },
        colorScheme: "dark",
        recordVideo: {
            dir: videoDir,
            size: { width: 1440, height: 1024 },
        },
    });

    const page = await context.newPage();
    page.setDefaultTimeout(30_000);
    const video = page.video();
    const frameIndex = { value: 0 };

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.waitForTimeout(1300);
    await page.screenshot({ path: path.join(outputDir, "home-raw.png"), type: "png" });
    await holdFrames(page, framesDir, { count: 10, prefix: "home", nextIndexRef: frameIndex });

    await page.goto(`${baseUrl}/import`, { waitUntil: "networkidle" });
    await page.waitForSelector("#fileInput");
    await page.setInputFiles("#fileInput", demoCsvPath);
    await page.waitForFunction(() => {
        const button = document.getElementById("uploadButton");
        return button && !button.disabled;
    });
    await page.waitForTimeout(400);
    await holdFrames(page, framesDir, { count: 10, prefix: "import", nextIndexRef: frameIndex });

    await Promise.all([
        page.waitForSelector("#uploadResults .upload-result"),
        page.locator("#uploadButton").click(),
    ]);
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(outputDir, "upload-success-raw.png"), type: "png" });
    await holdFrames(page, framesDir, { count: 15, prefix: "upload-success", nextIndexRef: frameIndex });

    await page.goto(`${baseUrl}/review`, { waitUntil: "networkidle" });
    await page.waitForSelector("#transaction-table tbody tr");
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(outputDir, "review-raw.png"), type: "png" });
    await holdFrames(page, framesDir, { count: 10, prefix: "review", nextIndexRef: frameIndex });

    const firstRow = page.locator("#transaction-table tbody tr").first();
    const firstRowId = await firstRow.getAttribute("id");
    await firstRow.locator("button[type='submit']").click();
    if (firstRowId) {
        await page.waitForSelector(`#${firstRowId}`);
    }
    await page.waitForTimeout(700);
    await holdFrames(page, framesDir, { count: 15, prefix: "review-saved", nextIndexRef: frameIndex });

    await page.goto(`${baseUrl}/analytics`, { waitUntil: "networkidle" });
    await waitForAnalytics(page);
    await page.evaluate(() => {
        const header = [...document.querySelectorAll("h2")].find((element) =>
            element.textContent && element.textContent.includes("Category Analysis")
        );
        if (header) {
            const top = Math.max(0, header.getBoundingClientRect().top + window.scrollY - 120);
            window.scrollTo({ top, behavior: "instant" });
        }
    });
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(outputDir, "analytics-raw.png"), type: "png" });
    await holdFrames(page, framesDir, { count: 25, prefix: "analytics", nextIndexRef: frameIndex });

    await context.close();

    if (video) {
        const videoPath = await video.path();
        console.log(`Recorded video: ${videoPath}`);
    }

    await browser.close();
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
