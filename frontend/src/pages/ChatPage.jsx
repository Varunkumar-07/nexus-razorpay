import ChatView from "../components/ChatView";
import Header from "../components/Header";

export default function ChatPage() {
  return (
    <>
      <Header subtitle="Chat with the shopping assistant. Every order is bounded, confirmed, and logged." />
      <ChatView />
    </>
  );
}
