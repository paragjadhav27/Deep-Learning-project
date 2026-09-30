import { choosePhoto, errorAlert, expect, expectAccessible, FIXTURES, giveConsentWithKeyboard, test } from "./helpers";

test.describe("landing and policy pages", () => {
  test("landing explains all three tools and their limits @mobile", async ({ page }) => {
    const res = await page.goto("/");
    const csp = res?.headers()["content-security-policy"] ?? "";
    expect(csp).toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'/);
    expect(csp).not.toContain("unsafe-eval");

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    for (const name of ["Estimate age", "Estimate perceived presentation", "Preview age transformation"]) {
      await expect(page.getByRole("link", { name })).toBeVisible();
    }
    await expect(page.getByText(/says nothing about someone.s gender identity or sex/i)).toBeVisible();
    await expectAccessible(page, "landing");
  });

  for (const path of ["/privacy", "/responsible-use", "/model-cards"]) {
    test(`${path} is accessible`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      if (path === "/model-cards") await expect(page.getByText("yunet@2026may")).toBeVisible();
      await expectAccessible(page, path);
    });
  }

  test("skip link moves focus to main content", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeFocused();
  });
});

test.describe("age estimate", () => {
  test("full flow with keyboard consent, result, and deletion @mobile", async ({ page }) => {
    await page.goto("/tools/age");
    await expect(page.getByRole("note", { name: /demonstration mode/i })).toBeVisible();
    await expect(page.getByRole("button", { name: "Choose a photo" })).toBeDisabled();
    await expectAccessible(page, "age: initial");

    await giveConsentWithKeyboard(page);
    await choosePhoto(page, FIXTURES.portrait);
    await expectAccessible(page, "age: photo chosen");

    await page.getByRole("button", { name: /upload and estimate age/i }).click();
    const heading = page.getByRole("heading", { name: "Your result" });
    await expect(heading).toBeFocused();
    await expect(page.getByTestId("age-range")).toHaveText(/About \d+–\d+ years/);
    await expect(page.getByText("Placeholder (mock model)")).toBeVisible();
    await expect(page.getByText(/delete automatically in about \d+ minutes/i)).toBeVisible();
    await expectAccessible(page, "age: result");

    await page.getByRole("button", { name: "Delete photo and results" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expectAccessible(page, "age: delete dialog");
    await dialog.getByRole("button", { name: "Delete now" }).click();
    await expect(page.getByRole("heading", { name: "Deleted" })).toBeFocused();
  });

  test("a photo with no face is declined with guidance", async ({ page }) => {
    await page.goto("/tools/age");
    await giveConsentWithKeyboard(page);
    await choosePhoto(page, FIXTURES.noFace);
    await page.getByRole("button", { name: /upload and estimate age/i }).click();
    const alert = errorAlert(page);
    await expect(alert).toContainText("We couldn't find a face");
    await expect(alert.getByRole("button", { name: /different photo/i })).toBeVisible();
    await expectAccessible(page, "age: no-face error");
  });

  test("a group photo is declined, and cropping to one face fixes it", async ({ page }) => {
    await page.goto("/tools/age");
    await giveConsentWithKeyboard(page);
    await choosePhoto(page, FIXTURES.twoFaces);
    await page.getByRole("button", { name: /upload and estimate age/i }).click();
    await expect(errorAlert(page)).toContainText("We found more than one face");

    // Zoom 2×: the crop window is now half the width, so only one portrait fits.
    await page.getByRole("button", { name: "Adjust framing" }).click();
    const zoom = page.getByRole("slider", { name: "Zoom" });
    await zoom.focus();
    for (let i = 0; i < 20; i++) await page.keyboard.press("ArrowRight"); // 1.0 → 2.0
    await expect(zoom).toHaveAttribute("aria-valuetext", "200 percent");
    // Left edge and top: the face sits in the upper half of each portrait.
    await page.getByRole("slider", { name: "Horizontal position" }).focus();
    await page.keyboard.press("Home");
    await page.getByRole("slider", { name: "Vertical position" }).focus();
    await page.keyboard.press("Home");
    await expectAccessible(page, "age: framing controls");

    await page.getByRole("button", { name: /upload and estimate age/i }).click();
    await expect(page.getByRole("heading", { name: "Your result" })).toBeVisible();
  });
});

test.describe("perceived presentation", () => {
  test("uses presentation language, never identity", async ({ page }) => {
    await page.goto("/tools/presentation");
    await giveConsentWithKeyboard(page);
    await choosePhoto(page, FIXTURES.portrait);
    await page.getByRole("button", { name: /upload and estimate perceived presentation/i }).click();
    const outcome = page.getByTestId("presentation-outcome");
    await expect(outcome).toHaveText(/The model (perceives|is uncertain)/);
    await expect(page.getByText(/says nothing about a person.s gender identity or sex/i)).toBeVisible();
    const body = (await page.locator("main").innerText()).toLowerCase();
    expect(body).not.toMatch(/\byou are\b|\bthis person is\b/);
    await expectAccessible(page, "presentation: result");
  });
});

test.describe("age transformation", () => {
  test("choose target, compare, download, regenerate without re-upload @mobile", async ({ page }) => {
    const uploads: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && new URL(r.url()).pathname === "/v1/sessions") uploads.push(r.url());
    });

    await page.goto("/tools/aging");
    await giveConsentWithKeyboard(page);
    await choosePhoto(page, FIXTURES.portrait);

    // Minor targets are shown but unavailable, with the reason.
    const child = page.getByRole("radio", { name: /child/i }).first();
    await expect(child).toBeDisabled();
    await expect(page.getByText(/pending a safety and legal review/i).first()).toBeVisible();

    await expect(page.getByRole("button", { name: /upload and preview/i })).toBeDisabled();
    await page.getByRole("radio", { name: /older adult/i }).first().check();
    await page.getByRole("button", { name: /upload and preview/i }).click();

    await expect(page.getByRole("heading", { name: "Your result" })).toBeFocused();
    await expect(page.getByText("Synthetic image", { exact: true })).toBeVisible();
    await expect(page.getByText(/Creative target:/)).toContainText("Older adult");
    const after = page.getByRole("img", { name: /synthetic illustration edited toward the older adult/i });
    await expect(after).toBeVisible();
    expect(await after.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);

    const comparison = page.getByRole("slider", { name: /comparison/i });
    await comparison.focus();
    await page.keyboard.press("ArrowRight");
    await expect(comparison).toHaveAttribute("aria-valuetext", "51% original, 49% synthetic");
    await expectAccessible(page, "aging: result");

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download synthetic image" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("facelens-synthetic-older_adult.jpg");

    // Regenerate with a different target: the same upload is reused.
    await page.getByRole("radio", { name: /middle-aged adult/i }).last().check();
    await page.getByRole("button", { name: "Generate again" }).click();
    await expect(page.getByText(/Creative target:/)).toContainText("Middle-aged adult");
    expect(uploads).toHaveLength(1);
  });
});
