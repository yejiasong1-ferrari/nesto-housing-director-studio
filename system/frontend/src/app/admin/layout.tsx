export const metadata = {
  title: "Nesto Ops · Admin Console",
  description: "Nesto housing director operations console",
};

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 antialiased">
      {children}
    </div>
  );
}
