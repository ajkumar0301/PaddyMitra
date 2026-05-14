import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView, DeleteView, DetailView, ListView, UpdateView,
)

from core.mixins import RoleRequiredMixin

from .forms import HookForm
from .models import Hook

log = logging.getLogger("irri")


class AdminMixin(RoleRequiredMixin):
    required_roles = ("Administrator",)


class HookListView(LoginRequiredMixin, ListView):
    model = Hook
    template_name = "hooks/list.html"
    context_object_name = "hooks"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Hook.objects.all()
        ctx["total"] = qs.count()
        ctx["active"] = qs.filter(status="Active").count()
        ctx["paused"] = qs.filter(status="Paused").count()
        ctx["messages_processed"] = sum(h.messages_processed_count for h in qs) or 0
        return ctx


class HookDetailView(LoginRequiredMixin, DetailView):
    model = Hook
    template_name = "hooks/detail.html"
    context_object_name = "hook"


class HookCreateView(AdminMixin, CreateView):
    model = Hook
    form_class = HookForm
    template_name = "hooks/form.html"
    success_url = reverse_lazy("hooks:list")


class HookUpdateView(AdminMixin, UpdateView):
    model = Hook
    form_class = HookForm
    template_name = "hooks/form.html"
    success_url = reverse_lazy("hooks:list")


class HookDeleteView(AdminMixin, DeleteView):
    model = Hook
    template_name = "hooks/confirm_delete.html"
    success_url = reverse_lazy("hooks:list")


@login_required
@require_POST
def toggle_hook(request, pk):
    role = getattr(request.user, "role", None)
    if not role or role.name != "Administrator":
        return HttpResponseForbidden("Not permitted.")
    hook = get_object_or_404(Hook, pk=pk)
    hook.status = "Paused" if hook.status == "Active" else "Active"
    hook.save()
    messages.info(request, f"Hook '{hook.name}' is now {hook.status}.")
    return redirect("hooks:list")


@method_decorator(csrf_exempt, name="dispatch")
class PickyAssistWebhookView(View):
    """
    Picky Assist WhatsApp webhook receiver.
    Body (JSON) expected to contain:
        {
          "from": "+91XXXXXXXXXX",
          "trigger_keyword": "DHAN",
          "message_type": "text" | "audio",
          "text": "...",              # when message_type == text
          "audio_url": "https://...", # when message_type == audio
          "district": "Bargarh"       # optional
        }
    """

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid json"}, status=400)

        trigger = (payload.get("trigger_keyword") or "").upper().strip()
        hook = Hook.objects.filter(trigger_keyword=trigger, status="Active").first()
        if not hook:
            return JsonResponse({"error": f"no active hook for keyword '{trigger}'"}, status=404)

        from queries.services.pipeline import process_incoming_message

        try:
            query = process_incoming_message(hook, payload)
            return JsonResponse({"status": "queued", "query_id": query.pk})
        except Exception as exc:
            log.exception("Webhook pipeline error")
            return JsonResponse({"error": str(exc)}, status=500)
