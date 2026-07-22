import { expect, test } from '@playwright/test';

const projectId = 'PROJ-EVIDENCE';
const moleculeId = 'MOL-00A50B1CFC';
const evidenceId = `DB:SYNTHESIS:${moleculeId}`;

test('molecule evidence tab displays a traceable synthesis source', async ({ page }) => {
  let evidenceRequestCount = 0;

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }

    const path = url.pathname.replace(/^\/api/, '');
    const fulfillJson = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });

    if (path.endsWith(`/projects/${projectId}/molecules/${moleculeId}`)) {
      await fulfillJson({
        molecule_id: moleculeId,
        smiles: 'CCO',
        scaffold: null,
        status: 'candidate_assessed',
        labels: [],
        source_agent: 'test',
      });
      return;
    }

    if (path.endsWith(`/projects/${projectId}/evidence-links`)) {
      evidenceRequestCount += 1;
      await fulfillJson([
        {
          evidence_id: evidenceId,
          molecule_id: moleculeId,
          chunk_id: null,
          claim_type: 'database_synthesis',
          confidence: 0.987,
          document_title: 'BRAF V600E synthesis record',
          source: 'AiZynthFinder',
          section: 'Retrosynthesis',
          rationale: 'AiZynthFinder found a 3-step synthesis route.',
          content: 'Commercial building-block selection.',
        },
      ]);
      return;
    }

    await fulfillJson([]);
  });

  await page.goto(`/projects/${projectId}/molecules/${moleculeId}`);
  await expect.poll(() => evidenceRequestCount).toBe(1);
  await page.getByRole('button', { name: '\u6587\u732e\u8bc1\u636e' }).click();

  const citation = page.locator('article.citation');
  await expect(citation).toContainText('BRAF V600E synthesis record');
  await expect(citation).toContainText('AiZynthFinder');
  await expect(citation).toContainText('Retrosynthesis');
  await expect(citation).toContainText('AiZynthFinder found a 3-step synthesis route.');
  await expect(citation).toContainText('Commercial building-block selection.');
});
