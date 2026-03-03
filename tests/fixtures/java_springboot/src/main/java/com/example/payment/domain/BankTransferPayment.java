package com.example.payment.domain;

import java.math.BigDecimal;

public class BankTransferPayment extends Payment {
    private String accountNumber;
    private String routingNumber;
    private String bankName;

    public BankTransferPayment(String id, BigDecimal amount, String currency,
                               String accountNumber, String routingNumber, String bankName) {
        super(id, amount, currency);
        this.accountNumber = accountNumber;
        this.routingNumber = routingNumber;
        this.bankName = bankName;
    }

    @Override
    public PaymentType getType() {
        return PaymentType.BANK_TRANSFER;
    }

    @Override
    public boolean validate() {
        return accountNumber != null && routingNumber != null && bankName != null;
    }

    public String getBankName() {
        return bankName;
    }
}
