from rest_framework import generics, permissions
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminOrReadOnly
from billing.models import Payment
from .models import Customer
from .serializers import CustomerSerializer


class CustomerListCreateView(generics.ListCreateAPIView):
    queryset = Customer.objects.all().order_by("-created_at")
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class CustomerDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class CustomerReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        invoices = customer.invoices.order_by("-invoice_date", "-id").values(
            "id", "invoice_number", "invoice_date", "payment_status", "total_amount"
        )
        payments = Payment.objects.filter(customer=customer).order_by("-payment_date", "-id").values(
            "id", "invoice_id", "amount", "payment_date", "notes"
        )
        return Response(
            {
                "customer_id": customer.id,
                "invoices": list(invoices),
                "payments": list(payments),
                "outstanding_balance": customer.outstanding_balance,
            }
        )
