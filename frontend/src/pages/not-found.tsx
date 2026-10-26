import { Compass, Home } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common/empty-state";

export function NotFoundPage() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <EmptyState
        icon={Compass}
        title="This console route does not exist"
        description="The URL may be stale or mistyped. Return to the operations overview to continue."
        action={
          <Button asChild variant="outline">
            <Link to="/">
              <Home className="h-4 w-4" aria-hidden="true" />
              Back to overview
            </Link>
          </Button>
        }
        className="max-w-xl"
      />
    </div>
  );
}
