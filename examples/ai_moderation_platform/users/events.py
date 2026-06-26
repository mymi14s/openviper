from openviper.db.events import model_event


async def send_email(user, event):
    """Example event handler that sends an email after a user is created."""
    print(f"User created: {user.username}")
    print("Sending email to moderators for review...", event)


@model_event.trigger("users.models.User.on_update")
async def on_user_updated(user, *, event):
    """Event handler for when a new user is created."""
    print(f"User updated: {user.username}")
    print("Triggering email notification...", event)
