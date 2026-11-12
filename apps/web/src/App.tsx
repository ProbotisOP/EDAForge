import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Loading } from "./components/ui";
import { ConnectPage } from "./pages/ConnectPage";
import { DataPage } from "./pages/DataPage";
import { DiscoverPage, RunPage } from "./pages/DiscoverPage";
import { FindingPage } from "./pages/FindingPage";
import { ProjectLayout } from "./pages/ProjectLayout";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ReportPage } from "./pages/ReportPage";

// The Data Universe draws with three.js; loading it with its page keeps it out of every other page.
const UniversePage = lazy(() => import("./pages/UniversePage").then((m) => ({ default: m.UniversePage })));

const SECTIONS = ["data", "connect", "discover", "report"];

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/p/:projectId" element={<ProjectLayout sections={SECTIONS} />}>
          <Route index element={<Navigate to="data" replace />} />
          <Route path="data" element={<DataPage />} />
          <Route path="data/:datasetId" element={<DataPage />} />
          <Route path="connect" element={<ConnectPage />} />
          <Route path="discover" element={<DiscoverPage />} />
          <Route path="discover/runs/:runId" element={<RunPage />} />
          <Route path="discover/runs/:runId/universe" element={<Suspense fallback={<Loading />}><UniversePage /></Suspense>} />
          <Route path="discover/runs/:runId/:findingId" element={<FindingPage />} />
          <Route path="report" element={<ReportPage />} />
          <Route path="report/:runId" element={<ReportPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
