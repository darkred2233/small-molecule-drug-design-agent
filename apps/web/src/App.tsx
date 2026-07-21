import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/AppShell';
import { MoleculeDetailPage } from '@/pages/MoleculeDetailPage';
import { ProjectDataPage } from '@/pages/ProjectDataPage';
import { ProjectOverviewPage } from '@/pages/ProjectOverviewPage';
import { ProjectSetupPage } from '@/pages/ProjectSetupPage';
import { ProjectsPage } from '@/pages/ProjectsPage';
import { RankingPage } from '@/pages/RankingPage';
import { RoundReportPage } from '@/pages/RoundReportPage';
import { RoundRunPage } from '@/pages/RoundRunPage';
import { StrategyPage } from '@/pages/StrategyPage';

export default function App() {
  return (
    <Routes>
      <Route path="/projects" element={<ProjectsPage />} />
      <Route path="/projects/new" element={<ProjectSetupPage />} />
      <Route path="/workspace" element={<Navigate to="/projects" replace />} />
      <Route path="/workspace/:projectId" element={<Navigate to="overview" replace />} />
      <Route path="/projects/:projectId" element={<AppShell />}>
        <Route path="overview" element={<ProjectOverviewPage />} />
        <Route path="data" element={<ProjectDataPage />} />
        <Route path="rounds/:roundId/strategy" element={<StrategyPage />} />
        <Route path="rounds/:roundId/run" element={<RoundRunPage />} />
        <Route path="rounds/:roundId/ranking" element={<RankingPage />} />
        <Route path="rounds/:roundId/report" element={<RoundReportPage />} />
        <Route path="molecules/:moleculeId" element={<MoleculeDetailPage />} />
        <Route index element={<Navigate to="overview" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  );
}
