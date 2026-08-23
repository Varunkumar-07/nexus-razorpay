import { Route, Routes } from "react-router-dom";
import CatalogPage from "./pages/CatalogPage";
import ChatPage from "./pages/ChatPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/products" element={<CatalogPage />} />
    </Routes>
  );
}
