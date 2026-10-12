from app.models.pay_run import PayRun


class PayRunLifecycle:

    ALLOWED_TRANSITIONS = {
        "draft": ["approved"],
        "approved": ["completed"],
        "completed": []
    }

    def transition(self, pay_run: PayRun, new_status: str):

        current_status = pay_run.status

        allowed = self.ALLOWED_TRANSITIONS.get(
            current_status, []
        )

        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition pay run "
                f"from '{current_status}' to '{new_status}'"
            )

        pay_run.status = new_status

        return pay_run