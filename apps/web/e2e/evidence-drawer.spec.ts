import { expect, test } from '@playwright/test';

const projectId = 'PROJ-EVIDENCE';
const moleculeId = 'MOL-00A50B1CFC';
const evidenceId = `DB:SYNTHESIS:${moleculeId}`;

test('database synthesis evidence is requested and displayed from a molecule route', async ({ page }) => {
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

    if (path.endsWith(`/projects/${projectId}/molecules/${moleculeId}/decision-cards`)) {
      await fulfillJson([
        {
          decision_id: 'DEC-EVIDENCE',
          trace_id: 'TRACE-EVIDENCE',
          molecule_id: moleculeId,
          decision: 'advance',
          title: 'Evidence regression test',
          summary: 'Summary',
          claim: 'Claim',
          support: [],
          risk: [],
          next_steps: [],
          uncertainty: null,
          confidence: 0.9,
          evidence_ids: [evidenceId],
          provenance: {},
        },
      ]);
      return;
    }

    if (path.includes('/evidence-links/')) {
      evidenceRequestCount += 1;
      await fulfillJson({
        evidence_id: evidenceId,
        molecule_id: moleculeId,
        chunk_id: null,
        claim_type: 'database_synthesis',
        confidence: 0.987,
        rationale: JSON.stringify({
          table: 'synthesis_routes',
          molecule_id: moleculeId,
          route_found: true,
          route_steps: 3,
          route_confidence: 0.987,
          buyable_building_blocks: 6,
          labels: ['route_found', 'aizynthfinder_route'],
          route_json: {
            tool_name: 'aizynthfinder',
            adapter_mode: 'aizynthfinder_docker',
            route_score: 0.987,
            runtime_seconds: 36.5,
            route_summary: 'AiZynthFinder found a route in 3 steps.',
            starting_materials: ['commercial aryl core', 'polar linker'],
            route_plan: [
              {
                step: 1,
                stage: 'Commercial building-block selection',
                operation: 'Select purchasable fragments.',
                output: 'Buyable fragment set.',
              },
            ],
            route_risks: ['No major AiZynthFinder route risk detected.'],
          },
        }),
      });
      return;
    }

    await fulfillJson([]);
  });

  await page.goto(`/workspace/${projectId}/molecules/${moleculeId}`);
  await page.getByText(evidenceId, { exact: true }).first().click();

  await expect.poll(() => evidenceRequestCount).toBe(1);
  await expect(page.getByText('合成路线', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('路线步数', { exact: true })).toBeVisible();
  await expect(page.getByText('AiZynthFinder found a route in 3 steps.', { exact: true })).toBeVisible();
  await expect(page.getByText('Commercial building-block selection', { exact: true })).toBeVisible();
  await expect(page.getByText('\u8def\u7ebf\u8bc4\u5206 0.987', { exact: true })).toBeVisible();
  await expect(page.getByText('\u7f6e\u4fe1\u5ea6 100%', { exact: true })).toHaveCount(0);

  await page.getByText('原始数据', { exact: true }).click();
  await expect(page.getByText(/synthesis_routes/).first()).toBeVisible();
});
