import { Inbox } from "lucide-react";

export default function EmptyState({ text = "No records found.", action }) {
  return (
    <div className="empty-state">
      <Inbox size={36} />
      <p>{text}</p>
      {action}
    </div>
  );
}
