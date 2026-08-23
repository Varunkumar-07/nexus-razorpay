import CatalogView from "../components/CatalogView";
import Header from "../components/Header";

export default function CatalogPage() {
  return (
    <>
      <Header subtitle="Full catalog — browse every product, grouped by category." />
      <CatalogView />
    </>
  );
}
