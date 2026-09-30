import { resolve } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test as base } from "@playwright/test";

export const FIXTURES = {
  portrait: resolve(__dirname, "fixtures/portrait.jpg"),
  twoFaces: resolve(__dirname, "fixtures/two-faces.jpg"),
  noFace: resolve(__dirname, "fixtures/no-face.png"),
};

/**
 * Every test fails on a CSP violation or an uncaught page error, so a broken nonce or
 * a runtime crash can't hide behind a passing assertion.
 */
export const test = base.extend<{ pageErrors: string[] }>({
  pageErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (msg) => {
        const text = msg.text();
        if (msg.type() === "error" && /Content Security Policy|Refused to/i.test(text)) errors.push(text);
      });
      page.on("pageerror", (err) => errors.push(err.message));
      await use(errors);
      expect(errors, "CSP violations or page errors").toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };

/** WCAG 2.2 AA via axe-core; any violation fails with a readable summary. */
export async function expectAccessible(page: Page, context: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.help} → ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
  expect(summary, `axe violations: ${context}`).toEqual([]);
}

/** The app's own error panel (Next also renders an empty role="alert" route announcer). */
export const errorAlert = (page: Page) => page.locator('[role="alert"][data-error-code]');

export async function giveConsentWithKeyboard(page: Page) {
  for (const name of [/permission/i, /18 or older/i, /uncertain and illustrative/i]) {
    const box = page.getByRole("checkbox", { name });
    await box.focus();
    await page.keyboard.press("Space");
    await expect(box).toBeChecked();
  }
}

export async function choosePhoto(page: Page, file: string) {
  await expect(page.getByRole("button", { name: "Choose a photo" })).toBeEnabled();
  await page.getByTestId("photo-input").setInputFiles(file);
  await expect(page.getByRole("img", { name: /preview of the area/i })).toBeVisible();
}
