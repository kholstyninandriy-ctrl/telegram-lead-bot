import ChatWidget from "@/components/ChatWidget";
import { agency } from "@/config/agency";

/**
 * The chat itself. This page is what the embedded iframe loads, so it renders
 * only the panel — the bubble that opens it lives on the host page (embed.js).
 */
export default function WidgetPage() {
  return (
    <main className="h-screen w-screen p-0">
      <ChatWidget
        agencyName={agency.name}
        assistantName={agency.assistantName}
        welcomeMessage={agency.welcomeMessage}
      />
    </main>
  );
}
