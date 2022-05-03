# Dymo Web Service Clone
This utility allows a PDF to be sent to a DYMO LabelWriter printer. It's very similar to the existing DYMO web service for label printing.

### Requirements
* Linux (support for other OSes would be trivial, but also unneccessary)
* Python 3.5 or greater

### Usage
When a print job is received, it should include a pdfUrl variable. This PDF is downloaded and sent to the DYMO printer.

To run the utility, use this command:

    python3 dymo-linux.py

Since the server uses a self-signed certificate, you must accept the certificate. Open [https://127.0.0.1:41951/](https://127.0.0.1:41951/) in your browser and allow the insecure connection. Once you see the status page, it's ready to go.

The server will wait for incoming print jobs and print them to the specified printer, or the system default if none are specified.
