from django.shortcuts import render, redirect, reverse, get_object_or_404
from django.http import HttpResponse
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate, login
from django.conf import settings
from django.db.models import Q
import razorpay

from .forms import UserForm, CustomerForm, AddressForm, SetAddressForm
from .models import Pet, Customer, CartItems, Address
from .models import Order, OrderItem


def register(request):
    template_name = "register.html"
    if request.method == "POST":
        uf = UserForm(request.POST)
        cf = CustomerForm(request.POST)
        print(uf.errors)
        print(cf.is_valid())
        if uf.is_valid() and cf.is_valid():
            u = uf.save()
            c = cf.save(commit=False)
            c.user = u
            c.save()
            return HttpResponse("User is registered")

        context = {
            'uf': uf,
            'cf': cf
        }
        return render(request, template_name, context=context)
    else:
        uf = UserForm()
        cf = CustomerForm()
        context = {
            'uf': uf,
            'cf': cf
        }
        return render(request, template_name, context=context)


def user_login(request):
    template_name = "login.html"
    if request.method == "POST":
        fn = AuthenticationForm(request=request, data=request.POST)
        if fn.is_valid():
            uname = fn.cleaned_data['username']
            upass = fn.cleaned_data['password']
            u = authenticate(username=uname, password=upass)
            if u is not None:
                login(request, u)
                return redirect('list_pets')
        context = {'form': fn}
    else:
        fn = AuthenticationForm()
        context = {'form': fn}
    return render(request, template_name, context=context)


def list_pets(request):
    template_name = "list_pets.html"
    pets = Pet.objects.all()
    context = collect_cart_details(request)
    context['pets'] = pets
    return render(request, template_name, context=context)


def pet_details(request, id):
    template_name = "pet_details.html"
    pet = Pet.objects.get(pk=id)
    context = collect_cart_details(request)
    context['pet'] = pet
    return render(request, template_name, context=context)


def add_to_cart(request, pet_id):
    cur_customer = Customer.objects.get(user=request.user)
    pet = Pet.objects.get(id=pet_id)
    print("Current customer:", cur_customer)
    print("Current Pet ID:", pet_id)
    print("Posted data:", request.POST)

    cart_items = CartItems.objects.filter(customer=cur_customer, pet=pet)
    print(cart_items)
    if len(cart_items) == 0:
        # Empty cart
        cart_item = CartItems.objects.create(customer=cur_customer, pet=pet)
    else:
        # Cart with existing pet
        cart_item = cart_items[0]

    # Updated quantity
    cart_item.quantity = request.POST['quantity']
    cart_item.save()

    return redirect('display_cart_items')


def collect_cart_details(request):
    cart_items_list = CartItems.objects.filter(customer__user=request.user)
    print("Cart items list:", cart_items_list)
    grand_total = 0
    for cart_item in cart_items_list:
        print("Quantity:", cart_item.quantity)
        print("Pet Price:", cart_item.pet.price)
        cart_item.item_price = cart_item.quantity * cart_item.pet.price
        grand_total = grand_total + cart_item.item_price

    details = {
        'cart': cart_items_list,
        'total_price': grand_total
    }

    return details


def display_cart_items(request):
    template_name = "cart_items.html"
    # Get cart details along with price, total price, grand total price
    context = collect_cart_details(request)
    context['qty_list'] = [n for n in range(1, 6)]
    return render(request, template_name, context=context)


def remove_from_cart(request, pet_id):
    pet = Pet.objects.get(id=pet_id)
    cart_item = CartItems.objects.get(customer__user=request.user.id, pet=pet)
    cart_item.delete()
    return redirect('display_cart_items')


def manage_addresses(request):
    template_name = "address.html"
    addr_list = Address.objects.all()
    context = collect_cart_details(request)
    context['addr_list'] = addr_list
    return render(request, template_name, context=context)


def add_address(request):
    template_name = "add_address.html"
    if request.method == "POST":
        af = AddressForm(request.POST)
        if af.is_valid():
            addr = af.save(commit=False)
            addr.customer = Customer.objects.get(user=request.user)
            addr.save()
            return redirect('manage_addresses')
        context = {
            'form': af
        }
        return render(request, template_name, context=context)
    else:
        af = AddressForm()
        context = {
            'form': af
        }
    return render(request, template_name, context=context)


def set_address(request):
    template_name = 'set_address.html'
    al = Address.objects.filter(customer__user=request.user)
    # customer__user__id = request.user.id
    if request.method == "POST":
        saf = SetAddressForm(request.POST)
        if saf.is_valid():
            aid = saf.cleaned_data['delivery_address']
            return redirect('order_review', sa_id=aid)
    else:
        sa = SetAddressForm()
        context = {
            'address_list': al,
            'form': sa
        }
        return render(request, template_name, context=context)


def order_review(request, sa_id):
    print("Shipping address id:", sa_id)
    template_name = "order_review.html"
    context = collect_cart_details(request)
    addr = Address.objects.get(id=sa_id)
    context['address'] = addr
    return render(request, template_name, context=context)


def clear_cart_details(request):
    cart_items_list = CartItems.objects.filter(customer__user=request.user)
    for item in cart_items_list:
        item.delete()


def checkout_order(request, sa_id):
    cart_items_list = collect_cart_details(request)['cart']
    customer = Customer.objects.filter(user=request.user)
    delivery_addr = Address.objects.filter(id=sa_id)
    if customer:
        order = Order(customer=customer[0], shipping_address=delivery_addr[0])
        order.save()
        for item in cart_items_list:
            OrderItem.objects.create(
                order=order,
                pet=item.pet,
                price=item.pet.price,
                quantity=item.quantity
            )
        # Empty the cart
        clear_cart_details(request)
        # Save order_id for future use in payment order page
        request.session['order_id'] = order.id
        # redirect for payment
        return redirect(reverse('payment_order'))
    else:
        return redirect(reverse('list_pets'))


# Initialize the razorpay client to capture the payment details
client = razorpay.Client(auth=(settings.RAZOR_KEY_ID, settings.RAZOR_KEY_SECRET))


def payment_order(request):
    template_name = 'payment_order.html'
    order_id = request.session.get('order_id')
    order = get_object_or_404(Order, id=order_id)
    amount_display = int(order.get_total_cost())
    amount_razorpay = amount_display * 100

    context = {
        'order_id': order_id,
        'public_key': settings.RAZOR_KEY_ID,
        'amount_razorpay': amount_razorpay,
        'amount_display': amount_display
    }

    return render(request, template_name, context=context)


def payment_process(request, order_id, amount):
    try:
        order = get_object_or_404(Order, id=order_id)
        payment_id = request.POST['razorpay_payment_id']
        print("Payment ID: ", payment_id)
        payment_client_capture = (client.payment.capture(payment_id, amount))
        print("Payment Client capture", payment_client_capture)
        payment_fetch = client.payment.fetch(payment_id)
        status = payment_fetch['status']
        print("Payment status: ", status)
        amount_fetch = payment_fetch['amount']
        print("Payment amount_fetch: ", amount_fetch)

        # Update Order table
        order.transaction_id = payment_id
        order.order_status = True

        context = {
            'amount': int(amount/100),
            'status': status,
            'transaction_id': payment_id
        }
        return render(request, 'done.html', context=context)

    except Exception as e:
        return HttpResponse("Payment has failed try again!!")


def search_pets(request):
    template_name = "list_pets.html"
    q = request.GET.get('q')
    query = Q(name__icontains=q) | Q(breed__icontains=q)
    pets = Pet.objects.filter(query)
    context = collect_cart_details(request)
    context['pets'] = pets
    return render(request, template_name, context=context)
