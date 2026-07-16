import { Routes, Route, Navigate } from 'react-router-dom';
import WorkspacePage from './pages/WorkspacePage';
import MoleculeDetailPage from './pages/MoleculeDetailPage';
import ReportPage from './pages/ReportPage';
import EvidenceDrawer from './components/EvidenceDrawer';

function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<Navigate to="/workspace" replace />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/workspace/:projectId" element={<WorkspacePage />} />
        <Route path="/workspace/:projectId/molecules/:moleculeId" element={<MoleculeDetailPage />} />
        <Route path="/workspace/:projectId/report" element={<ReportPage />} />
      </Routes>

      {/* Global Evidence Drawer - available on all pages */}
      <EvidenceDrawer />
    </>
  );
}

export default App;
