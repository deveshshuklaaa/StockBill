from django.template import Context, Template


INVOICE_TEMPLATE = """
<html>
  <body>
    <h1>Invoice {{ invoice.invoice_number }}</h1>
    {% if invoice.state == 'CANCELLED' %}<h2>CANCELLED</h2><p>{{ invoice.cancellation_reason }}</p>{% endif %}
    <p>Customer: {{ customer_name|default:'Walk-in' }}</p>
    <p>Date: {{ invoice.invoice_date }}</p>
    <table>
      <thead><tr><th>Item</th><th>Qty</th><th>Rate</th><th>Tax</th><th>Total</th></tr></thead>
      <tbody>
        {% for item in line_items %}
        <tr>
          <td>{{ item.product_name_snapshot|default:item.product.name }}</td>
          <td>{{ item.quantity }}</td>
          <td>{{ item.rate_charged }}</td>
          <td>{{ item.tax_rate }}%</td>
          <td>{{ item.line_total }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p><strong>Grand Total:</strong> {{ total }}</p>
  </body>
</html>
"""


def invoice_pdf_context(invoice):
    return {
        "invoice": invoice,
        "line_items": invoice.line_items.all(),
        "customer_name": invoice.customer_name_snapshot,
        "total": invoice.total_amount,
    }


def render_invoice_html(invoice):
    return Template(INVOICE_TEMPLATE).render(Context(invoice_pdf_context(invoice)))
