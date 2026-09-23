import AppSidebar from "@/components/AppSidebar";

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <AppSidebar />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}