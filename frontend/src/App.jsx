import { Route, Routes } from "react-router-dom";
import CatalogPage from "./pages/CatalogPage";
import ChatPage from "./pages/ChatPage";
import StatsPage from "./pages/StatsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/products" element={<CatalogPage />} />
      <Route path="/stats" element={<StatsPage />} />
    </Routes>
  );
}
