import Header from "../components/Header";
import StatsView from "../components/StatsView";

export default function StatsPage() {
  return (
    <>
      <Header subtitle="Business metrics, computed live from the Audit Log — every order, upsell, and rejection." />
      <StatsView />
    </>
  );
}
