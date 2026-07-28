import { expect, test } from '@playwright/test';

const projectId = 'PROJ-POSE';
const moleculeId = 'MOL-POSE-001';

test('molecule pose tab renders metadata stored in docking raw output', async ({ page }) => {
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }

    const path = url.pathname.replace(/^\/api/, '');
    const fulfillJson = (body: unknown) => route.fulfill({
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
        round_id: 'ROUND-POSE',
      });
      return;
    }

    if (path.endsWith(`/projects/${projectId}/docking-results`)) {
      await fulfillJson([{
        molecule_id: moleculeId,
        vina_score: -8.9,
        pose_file: 'poses/MOL-POSE-001.sdf',
        raw_output: {
          selected_pose_rank: 1,
          pose_count: 9,
          pose_selection_method: 'gnina_output_mode_1',
        },
      }]);
      return;
    }

    await fulfillJson([]);
  });

  await page.goto(`/projects/${projectId}/molecules/${moleculeId}`);
  await page.getByRole('button', { name: '\u6700\u4f73\u5bf9\u63a5\u6784\u8c61' }).click();

  await expect(page.getByText('\u6240\u9009 Pose')).toBeVisible();
  await expect(page.getByText('1', { exact: true })).toBeVisible();
  await expect(page.getByText('9', { exact: true })).toBeVisible();
  await expect(page.getByText('gnina_output_mode_1')).toBeVisible();
});
